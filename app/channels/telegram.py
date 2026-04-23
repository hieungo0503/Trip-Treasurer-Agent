"""
Telegram Bot channel — Phase 2 (alternative to Zalo).

Telegram Bot API: https://core.telegram.org/bots/api

Responsibilities:
  1. Verify webhook secret token (X-Telegram-Bot-Api-Secret-Token header)
  2. Parse incoming Update → normalize thành internal event dict
  3. Send text/photo reply qua Bot API
  4. Register/unregister webhook URL với Telegram

Supported update types:
  - message.text          → user_send_text
  - message.photo         → user_send_image (lấy file_id ảnh lớn nhất)
  - message.document      → user_send_image (nếu MIME là image/*)

Internal event format (giống Zalo để dùng chung orchestrator):
  {
      "event_name": "user_send_text" | "user_send_image",
      "user_id": str,       # chat_id (Telegram)
      "event_id": str,      # update_id
      "timestamp": int,     # epoch ms (message.date * 1000)
      "message": {
          "text": str | None,
          "attachments": [{"type": "image", "payload": {"file_id": str}}]
      }
  }

Setup:
  1. Nhắn @BotFather → /newbot → lấy TELEGRAM_BOT_TOKEN
  2. Đặt TELEGRAM_WEBHOOK_SECRET (chuỗi bất kỳ, tự chọn) vào .env
  3. Gọi POST /telegram/register_webhook để đăng ký URL với Telegram
     (hoặc chạy script scripts/register_telegram_webhook.py)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from app.config import get_settings
from app.observability.metrics import zalo_messages_received, zalo_send_errors
from app.reliability.circuit_breaker import zalo_circuit
from app.reliability.retry import zalo_retry

log = structlog.get_logger()

router = APIRouter(prefix="/webhook", tags=["telegram"])

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _api_url(token: str, method: str) -> str:
    return _TELEGRAM_API.format(token=token, method=method)


# ── Signature verification ─────────────────────────────────────────────────────

def verify_telegram_secret(
    expected_secret: str,
    received_secret: Optional[str],
) -> bool:
    """
    Telegram gửi header X-Telegram-Bot-Api-Secret-Token với mỗi webhook request.
    Giá trị = secret_token ta đăng ký lúc setWebhook.
    """
    if not expected_secret:
        return True  # chưa config → dev mode, bỏ qua
    if not received_secret:
        return False
    return received_secret == expected_secret


# ── Payload parsing ────────────────────────────────────────────────────────────

def parse_telegram_update(update: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Normalize Telegram Update → internal event dict.

    Telegram Update schema:
      update_id: int
      message: {
          message_id: int
          from: {id: int, first_name: str, username: str, ...}
          chat: {id: int, type: str}
          date: int  (epoch seconds)
          text: str | None
          photo: [{file_id, file_unique_id, width, height, file_size}, ...] | None
          document: {file_id, mime_type, ...} | None
      }

    Returns None cho callback_query, inline_query, ... (không hỗ trợ).
    """
    message = update.get("message") or update.get("edited_message")
    if not message:
        log.debug("telegram.parse.no_message", update_id=update.get("update_id"))
        return None

    chat_id = str(message.get("chat", {}).get("id", ""))
    if not chat_id:
        log.warning("telegram.parse.missing_chat_id")
        return None

    update_id = str(update.get("update_id", ""))
    timestamp = message.get("date", int(time.time())) * 1000  # → ms

    # Text message
    text = message.get("text") or message.get("caption")  # caption = text trên ảnh

    # Photo message: Telegram gửi nhiều size, lấy size lớn nhất (cuối list)
    photos = message.get("photo")
    document = message.get("document")
    attachments = []

    if photos:
        largest = max(photos, key=lambda p: p.get("file_size", 0))
        attachments.append({
            "type": "image",
            "payload": {
                "file_id": largest.get("file_id", ""),
                "width": largest.get("width", 0),
                "height": largest.get("height", 0),
            },
        })
    elif document and (document.get("mime_type", "").startswith("image/")):
        attachments.append({
            "type": "image",
            "payload": {
                "file_id": document.get("file_id", ""),
                "mime_type": document.get("mime_type", ""),
            },
        })

    if attachments:
        event_name = "user_send_image"
    elif text is not None:
        event_name = "user_send_text"
    else:
        log.debug("telegram.parse.unsupported_message_type", update_id=update_id)
        return None

    return {
        "event_name": event_name,
        "user_id": chat_id,
        "event_id": f"tg-{update_id}",
        "timestamp": timestamp,
        "message": {
            "text": text,
            "attachments": attachments,
        },
        "_channel": "telegram",  # orchestrator dùng để resolve send_fn
    }


# ── Send message ───────────────────────────────────────────────────────────────

@zalo_retry
async def send_telegram_message(chat_id: str, text: str) -> None:
    """
    Gửi text message tới Telegram user/group.

    Telegram giới hạn:
      - 4096 ký tự / message
      - 30 messages/second tới cùng 1 group
    """
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        log.warning("telegram.send.no_token", chat_id=chat_id)
        return

    # Truncate nếu quá dài
    if len(text) > 4000:
        text = text[:3997] + "..."

    if not zalo_circuit.can_attempt():
        log.warning("telegram.send.circuit_open", chat_id=chat_id)
        zalo_send_errors.labels(reason="circuit_open").inc()
        return

    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _api_url(token, "sendMessage"),
                json=payload,
            )
        data = resp.json()
        if not data.get("ok"):
            zalo_circuit.record_failure()
            zalo_send_errors.labels(reason=f"tg_api_error_{data.get('error_code')}").inc()
            log.error(
                "telegram.send.api_error",
                chat_id=chat_id,
                error_code=data.get("error_code"),
                description=data.get("description"),
            )
        else:
            zalo_circuit.record_success()
            log.debug("telegram.send.ok", chat_id=chat_id)
    except httpx.TimeoutException:
        zalo_circuit.record_failure()
        zalo_send_errors.labels(reason="timeout").inc()
        log.error("telegram.send.timeout", chat_id=chat_id)
        raise
    except Exception as e:
        zalo_circuit.record_failure()
        zalo_send_errors.labels(reason="exception").inc()
        log.error("telegram.send.error", chat_id=chat_id, error=str(e))
        raise


async def send_telegram_message_safe(chat_id: str, text: str) -> None:
    """Wrapper không raise — dùng trong orchestrator."""
    try:
        await send_telegram_message(chat_id, text)
    except Exception as e:
        log.error("telegram.send_safe.failed", chat_id=chat_id, error=str(e))


# ── Polling mode ──────────────────────────────────────────────────────────────

async def start_polling() -> None:
    """
    Long-polling loop — thay thế cho webhook khi không có HTTPS public.
    Tự động xoá webhook cũ (nếu có) trước khi bắt đầu poll.
    Gọi từ app lifespan, chạy mãi đến khi bị cancel.
    """
    from app.agent.orchestrator import handle_event

    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        log.warning("telegram.polling.no_token")
        return

    # Xoá webhook cũ để tránh conflict
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(_api_url(token, "deleteWebhook"), json={"drop_pending_updates": True})
        log.info("telegram.polling.webhook_cleared")
    except Exception as e:
        log.warning("telegram.polling.clear_webhook_failed", error=str(e))

    offset = 0
    log.info("telegram.polling.started")

    while True:
        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                resp = await client.get(
                    _api_url(token, "getUpdates"),
                    params={
                        "offset": offset,
                        "timeout": 30,
                        "allowed_updates": ["message", "edited_message"],
                    },
                )
            data = resp.json()

            if not data.get("ok"):
                log.error("telegram.polling.api_error", response=data)
                await asyncio.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                event = parse_telegram_update(update)
                if event:
                    zalo_messages_received.labels(event_type=f"tg_{event['event_name']}").inc()
                    try:
                        await handle_event(event)
                    except Exception as e:
                        log.error("telegram.polling.handler_error", error=str(e))

        except asyncio.CancelledError:
            log.info("telegram.polling.stopped")
            return
        except httpx.TimeoutException:
            pass  # long-poll timeout bình thường, tiếp tục
        except Exception as e:
            log.error("telegram.polling.exception", error=str(e))
            await asyncio.sleep(5)


# ── Webhook endpoint ───────────────────────────────────────────────────────────

@router.post("/telegram")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> dict:
    """
    Nhận Telegram Bot webhook updates.

    Telegram gửi POST với body là JSON Update object.
    Header X-Telegram-Bot-Api-Secret-Token chứa secret để verify.

    Contract: trả về 200 ngay, xử lý trong background.
    """
    from app.agent.orchestrator import handle_event

    settings = get_settings()

    # 1. Verify secret token
    if not verify_telegram_secret(
        settings.telegram_webhook_secret,
        x_telegram_bot_api_secret_token,
    ):
        log.warning("telegram.webhook.invalid_secret")
        raise HTTPException(status_code=403, detail="Invalid secret token")

    # 2. Parse body
    try:
        update = await request.json()
    except Exception as e:
        log.warning("telegram.webhook.invalid_json", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # 3. Parse update → internal event
    event = parse_telegram_update(update)
    if event is None:
        return {"ok": True, "note": "unsupported_update"}

    zalo_messages_received.labels(event_type=f"tg_{event['event_name']}").inc()

    # 4. Background xử lý
    background_tasks.add_task(_handle_event_background, handle_event, event)

    return {"ok": True}


async def _handle_event_background(handle_event_fn, event: dict) -> None:
    try:
        await handle_event_fn(event)
    except Exception as e:
        log.error(
            "telegram.webhook.handler_error",
            event_id=event.get("event_id"),
            chat_id=event.get("user_id"),
            error=str(e),
        )


# ── Webhook management ─────────────────────────────────────────────────────────

@router.post("/telegram/register_webhook")
async def register_webhook() -> dict:
    """
    Đăng ký webhook URL với Telegram.
    Gọi 1 lần sau khi deploy server có HTTPS.

    Telegram yêu cầu HTTPS (self-signed cert cũng được nếu upload cert).
    """
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not configured")

    webhook_url = settings.telegram_webhook_url
    if not webhook_url:
        raise HTTPException(status_code=500, detail="TELEGRAM_WEBHOOK_URL not configured")

    payload: dict[str, Any] = {
        "url": webhook_url,
        "allowed_updates": ["message", "edited_message"],
        "drop_pending_updates": True,
    }
    if settings.telegram_webhook_secret:
        payload["secret_token"] = settings.telegram_webhook_secret

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(_api_url(token, "setWebhook"), json=payload)

    data = resp.json()
    if data.get("ok"):
        log.info("telegram.webhook.registered", url=webhook_url)
        return {"ok": True, "description": data.get("description")}
    else:
        log.error("telegram.webhook.register_failed", response=data)
        raise HTTPException(status_code=500, detail=data.get("description", "Failed"))


@router.delete("/telegram/register_webhook")
async def unregister_webhook() -> dict:
    """Xoá webhook (dùng khi chuyển sang polling hoặc đổi server)."""
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not configured")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(_api_url(token, "deleteWebhook"))

    data = resp.json()
    return {"ok": data.get("ok"), "description": data.get("description")}


@router.get("/telegram/webhook_info")
async def webhook_info() -> dict:
    """Xem trạng thái webhook hiện tại (debug)."""
    settings = get_settings()
    token = settings.telegram_bot_token
    if not token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not configured")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_api_url(token, "getWebhookInfo"))

    return resp.json()
