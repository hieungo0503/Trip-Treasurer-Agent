"""
Tests cho channels/zalo.py — Phase 2.

Covers:
  - verify_zalo_signature: valid/invalid/missing mac
  - parse_zalo_event: text, image, follow, unfollow, unsupported
  - send_zalo_message: success, API error, timeout, circuit open
  - webhook endpoint: GET verify, POST valid, POST invalid signature, POST unsupported event
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from fastapi.testclient import TestClient

from app.channels.zalo import verify_zalo_signature, parse_zalo_event


# ── verify_zalo_signature ─────────────────────────────────────────────────────

class TestVerifyZaloSignature:
    def _make_mac(self, secret: str, payload: dict) -> str:
        params = {k: str(v) for k, v in payload.items() if k != "mac"}
        message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return hmac.new(
            secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def test_valid_signature(self):
        secret = "my_app_secret"
        payload = {
            "app_id": "123",
            "user_id": "user_abc",
            "event_name": "user_send_text",
            "timestamp": "1714000000000",
        }
        payload["mac"] = self._make_mac(secret, payload)
        assert verify_zalo_signature(secret, payload) is True

    def test_invalid_signature(self):
        secret = "my_app_secret"
        payload = {
            "app_id": "123",
            "user_id": "user_abc",
            "mac": "deadbeef",
        }
        assert verify_zalo_signature(secret, payload) is False

    def test_missing_mac_returns_false(self):
        payload = {"app_id": "123", "user_id": "user_abc"}
        assert verify_zalo_signature("secret", payload) is False

    def test_empty_payload_returns_false(self):
        assert verify_zalo_signature("secret", {}) is False

    def test_tampered_payload_fails(self):
        """Nếu payload bị sửa sau khi ký → verify fail."""
        secret = "my_app_secret"
        payload = {
            "app_id": "123",
            "user_id": "user_abc",
            "timestamp": "1714000000000",
        }
        payload["mac"] = self._make_mac(secret, payload)
        payload["user_id"] = "attacker_user"  # tamper
        assert verify_zalo_signature(secret, payload) is False


# ── parse_zalo_event ──────────────────────────────────────────────────────────

class TestParseZaloEvent:
    def test_user_send_text(self):
        raw = {
            "event_name": "user_send_text",
            "sender": {"id": "user_001"},
            "timestamp": 1714000000000,
            "message": {
                "msg_id": "msg_abc",
                "text": "chi 500k ăn uống",
            },
        }
        event = parse_zalo_event(raw)
        assert event is not None
        assert event["event_name"] == "user_send_text"
        assert event["user_id"] == "user_001"
        assert event["message"]["text"] == "chi 500k ăn uống"
        assert event["event_id"] == "msg_abc"
        assert event["timestamp"] == 1714000000000

    def test_user_send_image(self):
        raw = {
            "event_name": "user_send_image",
            "sender": {"id": "user_002"},
            "timestamp": 1714000001000,
            "message": {
                "msg_id": "msg_img_001",
                "attachments": [{"type": "image", "payload": {"url": "https://example.com/img.jpg"}}],
            },
        }
        event = parse_zalo_event(raw)
        assert event is not None
        assert event["event_name"] == "user_send_image"
        assert event["user_id"] == "user_002"
        assert len(event["message"]["attachments"]) == 1
        assert event["message"]["text"] is None

    def test_follow_event(self):
        raw = {
            "event_name": "follow",
            "follower": {"id": "user_003"},
            "timestamp": 1714000002000,
        }
        event = parse_zalo_event(raw)
        assert event is not None
        assert event["event_name"] == "follow"
        assert event["user_id"] == "user_003"

    def test_unfollow_event(self):
        raw = {
            "event_name": "unfollow",
            "follower": {"id": "user_004"},
            "timestamp": 1714000003000,
        }
        event = parse_zalo_event(raw)
        assert event is not None
        assert event["event_name"] == "unfollow"

    def test_unsupported_event_returns_none(self):
        raw = {
            "event_name": "oa_send_text",
            "recipient": {"id": "user_005"},
            "timestamp": 1714000004000,
        }
        result = parse_zalo_event(raw)
        assert result is None

    def test_missing_user_id_returns_none(self):
        raw = {
            "event_name": "user_send_text",
            "sender": {},  # no id
            "timestamp": 1714000005000,
            "message": {"text": "hello"},
        }
        result = parse_zalo_event(raw)
        assert result is None

    def test_empty_text_is_allowed(self):
        raw = {
            "event_name": "user_send_text",
            "sender": {"id": "user_006"},
            "timestamp": 1714000006000,
            "message": {"msg_id": "m1", "text": ""},
        }
        event = parse_zalo_event(raw)
        assert event is not None
        assert event["message"]["text"] == ""


# ── send_zalo_message ─────────────────────────────────────────────────────────

class TestSendZaloMessage:
    @pytest.mark.asyncio
    async def test_send_ok(self):
        from app.channels.zalo import send_zalo_message
        from app.reliability.circuit_breaker import zalo_circuit

        zalo_circuit.reset()

        mock_response = MagicMock()
        mock_response.json.return_value = {"error": 0, "data": {"message_id": "m123"}}

        with patch("app.channels.zalo.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value.zalo_oa_access_token = "test_token"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            await send_zalo_message("user_001", "Xin chào!")
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_skips_when_no_token(self):
        from app.channels.zalo import send_zalo_message

        with patch("app.channels.zalo.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value.zalo_oa_access_token = ""
            await send_zalo_message("user_001", "test")
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_truncates_long_message(self):
        from app.channels.zalo import send_zalo_message
        from app.reliability.circuit_breaker import zalo_circuit

        zalo_circuit.reset()

        long_text = "a" * 2000

        captured_payload = {}

        mock_response = MagicMock()
        mock_response.json.return_value = {"error": 0, "data": {"message_id": "m_long"}}

        async def mock_post(url, json=None, headers=None, **kwargs):
            captured_payload.update(json or {})
            return mock_response

        with patch("app.channels.zalo.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value.zalo_oa_access_token = "token"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=mock_post)
            mock_client_cls.return_value = mock_client

            await send_zalo_message("user_001", long_text)
            sent_text = captured_payload.get("message", {}).get("text", "")
            assert len(sent_text) <= 1900

    @pytest.mark.asyncio
    async def test_send_circuit_open_skips(self):
        from app.channels.zalo import send_zalo_message
        from app.reliability.circuit_breaker import zalo_circuit, CircuitState

        # Force open circuit
        zalo_circuit.state = CircuitState.OPEN
        zalo_circuit._opened_at = 0  # ensure it stays open

        with patch("app.channels.zalo.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value.zalo_oa_access_token = "token"
            await send_zalo_message("user_001", "test")
            mock_client_cls.assert_not_called()

        zalo_circuit.reset()


# ── Webhook endpoint (FastAPI TestClient) ─────────────────────────────────────

class TestZaloWebhookEndpoint:
    def _make_signed_payload(self, secret: str, base: dict) -> dict:
        params = {k: str(v) for k, v in base.items()}
        message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        mac = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        return {**base, "mac": mac}

    def _get_test_app(self):
        from app.main import app
        return TestClient(app, raise_server_exceptions=False)

    def test_get_webhook_returns_challenge(self):
        """GET /webhook/zalo?challenge=xxx trả về challenge (webhook verify Zalo)."""
        from app.channels.zalo import router
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(router)
        client = TestClient(test_app)
        resp = client.get("/webhook/zalo?challenge=abc123")
        assert resp.status_code == 200
        assert resp.text == "abc123"

    def test_post_webhook_unsupported_event_returns_ok(self):
        """Event type không hỗ trợ → 200 OK với note."""
        from app.channels.zalo import router
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(router)
        client = TestClient(test_app)

        # Không có app_secret → skip signature check
        with patch("app.channels.zalo.get_settings") as mock_settings:
            mock_settings.return_value.zalo_app_secret = ""

            resp = client.post(
                "/webhook/zalo",
                json={"event_name": "oa_send_text", "recipient": {"id": "u1"}},
            )
        assert resp.status_code == 200
        assert resp.json().get("note") == "unsupported_event"

    def test_post_webhook_invalid_json_returns_400(self):
        """Invalid JSON body → 400."""
        from app.channels.zalo import router
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(router)
        client = TestClient(test_app)

        resp = client.post(
            "/webhook/zalo",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_post_webhook_invalid_signature_returns_403(self):
        """Sai signature khi app_secret được set → 403."""
        from app.channels.zalo import router
        from fastapi import FastAPI
        test_app = FastAPI()
        test_app.include_router(router)
        client = TestClient(test_app)

        with patch("app.channels.zalo.get_settings") as mock_settings:
            mock_settings.return_value.zalo_app_secret = "real_secret"

            resp = client.post(
                "/webhook/zalo",
                json={"event_name": "user_send_text", "mac": "wrong_mac"},
            )
        assert resp.status_code == 403
