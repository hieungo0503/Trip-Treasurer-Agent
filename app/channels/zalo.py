"""
Zalo OA channel — Phase 2.

Responsibilities:
  1. Verify Zalo webhook signature (HMAC-SHA256)
  2. Parse incoming webhook payload → normalize to internal event dict
  3. Send text/image messages via Zalo OA Messaging API
  4. Refresh OA access token when expired

Zalo OA API reference:
  - Send message: POST https://openapi.zalo.me/v3.0/oa/message/cs
  - Get access token: POST https://oauth.zaloapp.com/v4/oa/access_token

Signature verification (Zalo webhook):
  mac = HMAC-SHA256(app_secret, "app_id={app_id}&user_id={user_id}&...")
  where the string is sorted query params of the webhook JSON (excluding mac).

Zalo docs: https://developers.zalo.me/docs/official-account/webhook
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Optional

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response

from app.config import get_settings
from app.observability.metrics import zalo_messages_received, zalo_send_errors
from app.reliability.circuit_breaker import zalo_circuit
from app.reliability.retry import zalo_retry

log = structlog.get_logger()

router = APIRouter(prefix="/webhook", tags=["zalo"])

# ── Zalo API base URLs ─────────────────────────────────────────────────────────

_ZALO_SEND_URL = "https://openapi.zalo.me/v3.0/oa/message/cs"
_ZALO_TOKEN_URL = "https://oauth.zaloapp.com/v4/oa/access_token"
_ZALO_SEND_IMAGE_URL = "https://openapi.zalo.me/v2.0/oa/message"


# ── Signature verification ─────────────────────────────────────────────────────

def verify_zalo_signature(app_secret: str, payload: dict[str, Any]) -> bool:
    """
    Verify Zalo OA webhook HMAC-SHA256 signature.

    Zalo signs the webhook body: for each event in the `data` list, the `mac`
    field is computed as:
        HMAC-SHA256(app_secret, "app_id={app_id}&user_id={user_id}&...")
    where the query string is built from sorted key=value pairs of the event
    fields (excluding `mac` itself).

    Returns True if signature matches, False otherwise.
    """
    received_mac = payload.get("mac", "")
    if not received_mac:
        return False

    # Build canonical message string: sorted params excluding mac
    params = {k: str(v) for k, v in payload.items() if k != "mac"}
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))

    expected = hmac.new(
        app_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, received_mac)


# ── Payload parsing ────────────────────────────────────────────────────────────

def parse_zalo_event(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Normalize Zalo webhook payload → internal event dict.

    Supported event types:
      - user_send_text (event_name = "user_send_text")
      - user_send_image (event_name = "user_send_image")
      - follow / unfollow

    Returns None for unsupported event types.

    Internal event format:
    {
        "event_name": "user_send_text" | "user_send_image" | "follow" | "unfollow",
        "user_id": str,           # Zalo user ID
        "event_id": str,          # unique message/event ID for idempotency
        "timestamp": int,         # epoch ms
        "message": {
            "text": str | None,
            "attachments": [...]  # for images
        }
    }
    """
    event_name = raw.get("event_name", "")
    sender = raw.get("sender", {})
    user_id = sender.get("id", "") or raw.get("follower", {}).get("id", "")
    timestamp = raw.get("timestamp", 0)
    message_id = raw.get("message", {}).get("msg_id", "") or raw.get("event_id", "")

    if not user_id:
        log.warning("zalo.parse.missing_user_id", zalo_event=event_name)
        return None

    if event_name == "user_send_text":
        text = raw.get("message", {}).get("text", "")
        return {
            "event_name": "user_send_text",
            "user_id": user_id,
            "event_id": message_id,
            "timestamp": timestamp,
            "message": {"text": text, "attachments": []},
        }

    if event_name == "user_send_image":
        attachments = raw.get("message", {}).get("attachments", [])
        return {
            "event_name": "user_send_image",
            "user_id": user_id,
            "event_id": message_id,
            "timestamp": timestamp,
            "message": {"text": None, "attachments": attachments},
        }

    if event_name in ("follow", "unfollow"):
        return {
            "event_name": event_name,
            "user_id": user_id,
            "event_id": f"{event_name}-{user_id}-{timestamp}",
            "timestamp": timestamp,
            "message": {"text": None, "attachments": []},
        }

    log.info("zalo.parse.unsupported_event", event_name=event_name)
    return None


# ── Send message ───────────────────────────────────────────────────────────────

@zalo_retry
async def send_zalo_message(user_id: str, text: str) -> None:
    """
    Send text message to a Zalo user via OA Messaging API.
    Applies retry + circuit breaker.

    Zalo limits:
      - Message must be < 2000 chars.
      - Rate: 60 messages/minute per OA.
    """
    settings = get_settings()
    token = settings.zalo_oa_access_token
    if not token:
        log.warning("zalo.send.no_token", user_id=user_id)
        return

    # Truncate nếu quá dài (Zalo giới hạn 2000 ký tự)
    if len(text) > 1900:
        text = text[:1897] + "..."

    payload = {
        "recipient": {"user_id": user_id},
        "message": {"text": text},
    }

    if not zalo_circuit.can_attempt():
        log.warning("zalo.send.circuit_open", user_id=user_id)
        zalo_send_errors.labels(reason="circuit_open").inc()
        return

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _ZALO_SEND_URL,
                json=payload,
                headers={
                    "access_token": token,
                    "Content-Type": "application/json",
                },
            )
        data = resp.json()
        if data.get("error") != 0:
            zalo_circuit.record_failure()
            zalo_send_errors.labels(reason=f"api_error_{data.get('error')}").inc()
            log.error(
                "zalo.send.api_error",
                user_id=user_id,
                error=data.get("error"),
                message=data.get("message"),
            )
        else:
            zalo_circuit.record_success()
            log.debug("zalo.send.ok", user_id=user_id, msg_id=data.get("data", {}).get("message_id"))
    except httpx.TimeoutException:
        zalo_circuit.record_failure()
        zalo_send_errors.labels(reason="timeout").inc()
        log.error("zalo.send.timeout", user_id=user_id)
        raise
    except Exception as e:
        zalo_circuit.record_failure()
        zalo_send_errors.labels(reason="exception").inc()
        log.error("zalo.send.error", user_id=user_id, error=str(e))
        raise


async def send_zalo_message_safe(user_id: str, text: str) -> None:
    """Wrapper không raise — dùng trong orchestrator để không fail request."""
    try:
        await send_zalo_message(user_id, text)
    except Exception as e:
        log.error("zalo.send_safe.failed", user_id=user_id, error=str(e))


# ── Token refresh ──────────────────────────────────────────────────────────────

async def refresh_oa_access_token() -> Optional[str]:
    """
    Refresh Zalo OA access token dùng refresh_token.
    Gọi thủ công hoặc từ cron job (token hết hạn sau 90 ngày).
    Trả về access_token mới hoặc None nếu fail.
    """
    settings = get_settings()
    if not settings.zalo_app_id or not settings.zalo_app_secret:
        log.error("zalo.refresh_token.missing_credentials")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _ZALO_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "app_id": settings.zalo_app_id,
                    "refresh_token": settings.zalo_oa_refresh_token,
                },
                headers={
                    "secret_key": settings.zalo_app_secret,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        data = resp.json()
        new_token = data.get("access_token")
        if new_token:
            log.info("zalo.refresh_token.ok", expires_in=data.get("expires_in"))
            return new_token
        log.error("zalo.refresh_token.failed", response=data)
        return None
    except Exception as e:
        log.error("zalo.refresh_token.error", error=str(e))
        return None


# ── Webhook endpoint ───────────────────────────────────────────────────────────

@router.get("/zalo")
async def zalo_webhook_verify(request: Request) -> Response:
    """
    Zalo calls GET to verify webhook URL ownership.
    Respond with the challenge token.
    """
    challenge = request.query_params.get("challenge", "")
    log.info("zalo.webhook.verify", challenge=challenge[:20] if challenge else "")
    return Response(content=challenge, media_type="text/plain")


@router.post("/zalo")
async def zalo_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Receive Zalo OA webhook events.

    Contract:
    - Must return 200 within 2s (Zalo times out at 5s).
    - Actual processing happens in background task.
    - Signature is verified before enqueue.
    """
    from app.agent.orchestrator import handle_event

    settings = get_settings()

    # 1. Read raw body
    try:
        body_bytes = await request.body()
        body_json = json.loads(body_bytes)
    except (json.JSONDecodeError, Exception) as e:
        log.warning("zalo.webhook.invalid_json", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # 2. Verify signature (skip nếu app_secret chưa cấu hình — dev mode)
    if settings.zalo_app_secret:
        if not verify_zalo_signature(settings.zalo_app_secret, body_json):
            log.warning("zalo.webhook.invalid_signature", user=body_json.get("sender", {}).get("id"))
            raise HTTPException(status_code=403, detail="Invalid signature")

    # 3. Parse event
    event = parse_zalo_event(body_json)
    if event is None:
        return {"ok": True, "note": "unsupported_event"}

    zalo_messages_received.labels(event_type=event["event_name"]).inc()

    # 4. Enqueue in background (return 200 immediately)
    background_tasks.add_task(_handle_event_background, handle_event, event)

    return {"ok": True}


async def _handle_event_background(handle_event_fn, event: dict) -> None:
    """Background handler — gọi orchestrator, gửi reply qua Zalo."""
    try:
        await handle_event_fn(event)
    except Exception as e:
        log.error(
            "zalo.webhook.handler_error",
            event_id=event.get("event_id"),
            user_id=event.get("user_id"),
            error=str(e),
        )
