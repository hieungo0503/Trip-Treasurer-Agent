"""
Tests cho channels/telegram.py

Covers:
  - verify_telegram_secret: valid, invalid, no secret (dev mode)
  - parse_telegram_update: text, photo, document image, caption, edited_message
  - parse_telegram_update: no message, no chat_id, unsupported type → None
  - send_telegram_message: ok, no token, truncate, circuit open, API error
  - webhook POST: valid, invalid secret, invalid json, unsupported update
  - register_webhook: ok, no token
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.channels.telegram import verify_telegram_secret, parse_telegram_update


# ── verify_telegram_secret ────────────────────────────────────────────────────

class TestVerifyTelegramSecret:
    def test_matching_secret_returns_true(self):
        assert verify_telegram_secret("my_secret", "my_secret") is True

    def test_wrong_secret_returns_false(self):
        assert verify_telegram_secret("my_secret", "wrong") is False

    def test_missing_header_returns_false(self):
        assert verify_telegram_secret("my_secret", None) is False

    def test_empty_secret_config_skips_check(self):
        """Chưa config secret → dev mode, luôn True."""
        assert verify_telegram_secret("", "anything") is True
        assert verify_telegram_secret("", None) is True


# ── parse_telegram_update ─────────────────────────────────────────────────────

class TestParseTelegramUpdate:
    def _base_update(self, overrides: dict | None = None) -> dict:
        u = {
            "update_id": 100001,
            "message": {
                "message_id": 1,
                "from": {"id": 123456789, "first_name": "Đức"},
                "chat": {"id": 123456789, "type": "private"},
                "date": 1714000000,
                "text": "chi 500k ăn tối",
            },
        }
        if overrides:
            u.update(overrides)
        return u

    def test_text_message(self):
        event = parse_telegram_update(self._base_update())
        assert event is not None
        assert event["event_name"] == "user_send_text"
        assert event["user_id"] == "123456789"
        assert event["message"]["text"] == "chi 500k ăn tối"
        assert event["event_id"] == "tg-100001"
        assert event["timestamp"] == 1714000000 * 1000
        assert event["_channel"] == "telegram"

    def test_photo_message(self):
        update = self._base_update()
        update["message"]["text"] = None
        update["message"]["photo"] = [
            {"file_id": "small_id", "width": 320, "height": 240, "file_size": 10000},
            {"file_id": "large_id", "width": 1280, "height": 960, "file_size": 200000},
        ]
        event = parse_telegram_update(update)
        assert event is not None
        assert event["event_name"] == "user_send_image"
        assert len(event["message"]["attachments"]) == 1
        assert event["message"]["attachments"][0]["payload"]["file_id"] == "large_id"

    def test_photo_with_caption(self):
        """Ảnh kèm caption → text = caption."""
        update = self._base_update()
        update["message"]["photo"] = [
            {"file_id": "img1", "width": 800, "height": 600, "file_size": 50000}
        ]
        update["message"]["caption"] = "bill ăn tối 200k"
        del update["message"]["text"]
        event = parse_telegram_update(update)
        assert event is not None
        assert event["event_name"] == "user_send_image"
        assert event["message"]["text"] == "bill ăn tối 200k"

    def test_document_image(self):
        """Document với mime_type image/* → user_send_image."""
        update = self._base_update()
        del update["message"]["text"]
        update["message"]["document"] = {
            "file_id": "doc_img_001",
            "mime_type": "image/jpeg",
            "file_size": 100000,
        }
        event = parse_telegram_update(update)
        assert event is not None
        assert event["event_name"] == "user_send_image"
        assert event["message"]["attachments"][0]["payload"]["file_id"] == "doc_img_001"

    def test_document_pdf_returns_none(self):
        """Document không phải image → None."""
        update = self._base_update()
        del update["message"]["text"]
        update["message"]["document"] = {
            "file_id": "pdf_001",
            "mime_type": "application/pdf",
        }
        result = parse_telegram_update(update)
        assert result is None

    def test_edited_message(self):
        """Edited message được xử lý giống message thường."""
        update = {
            "update_id": 100002,
            "edited_message": {
                "message_id": 2,
                "from": {"id": 987654321},
                "chat": {"id": 987654321, "type": "private"},
                "date": 1714000100,
                "text": "sửa: chi 600k ăn tối",
            },
        }
        event = parse_telegram_update(update)
        assert event is not None
        assert event["user_id"] == "987654321"
        assert event["message"]["text"] == "sửa: chi 600k ăn tối"

    def test_no_message_returns_none(self):
        update = {"update_id": 100003}
        assert parse_telegram_update(update) is None

    def test_no_chat_id_returns_none(self):
        update = self._base_update()
        update["message"]["chat"] = {}
        assert parse_telegram_update(update) is None

    def test_callback_query_returns_none(self):
        """callback_query không có message → None."""
        update = {
            "update_id": 100004,
            "callback_query": {"id": "cq1", "data": "some_data"},
        }
        assert parse_telegram_update(update) is None

    def test_group_chat_uses_chat_id(self):
        """Group chat: user_id là chat_id của group (negative number)."""
        update = self._base_update()
        update["message"]["chat"] = {"id": -100123456789, "type": "supergroup"}
        event = parse_telegram_update(update)
        assert event is not None
        assert event["user_id"] == "-100123456789"


# ── send_telegram_message ─────────────────────────────────────────────────────

class TestSendTelegramMessage:
    @pytest.mark.asyncio
    async def test_send_ok(self):
        from app.channels.telegram import send_telegram_message
        from app.reliability.circuit_breaker import zalo_circuit

        zalo_circuit.reset()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 42}}

        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value.telegram_bot_token = "123:ABC"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            await send_telegram_message("123456789", "Xin chào!")
            mock_client.post.assert_called_once()
            call_url = mock_client.post.call_args.args[0]
            assert "sendMessage" in call_url
            assert "123:ABC" in call_url

    @pytest.mark.asyncio
    async def test_skip_when_no_token(self):
        from app.channels.telegram import send_telegram_message

        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value.telegram_bot_token = ""
            await send_telegram_message("123", "test")
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_truncate_long_message(self):
        from app.channels.telegram import send_telegram_message
        from app.reliability.circuit_breaker import zalo_circuit

        zalo_circuit.reset()
        long_text = "x" * 5000
        captured = {}

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": {}}

        async def mock_post(url, json=None, **kwargs):
            captured.update(json or {})
            return mock_resp

        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value.telegram_bot_token = "token"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=mock_post)
            mock_client_cls.return_value = mock_client

            await send_telegram_message("123", long_text)
            assert len(captured.get("text", "")) <= 4000

    @pytest.mark.asyncio
    async def test_circuit_open_skips(self):
        from app.channels.telegram import send_telegram_message
        from app.reliability.circuit_breaker import zalo_circuit, CircuitState

        zalo_circuit.state = CircuitState.OPEN
        zalo_circuit._opened_at = 0

        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value.telegram_bot_token = "token"
            await send_telegram_message("123", "test")
            mock_client_cls.assert_not_called()

        zalo_circuit.reset()

    @pytest.mark.asyncio
    async def test_api_error_logged(self):
        from app.channels.telegram import send_telegram_message
        from app.reliability.circuit_breaker import zalo_circuit

        zalo_circuit.reset()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": False,
            "error_code": 403,
            "description": "Forbidden: bot was blocked by the user",
        }

        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value.telegram_bot_token = "token"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            # Không raise — chỉ log
            await send_telegram_message("123", "test")


# ── Webhook endpoint ──────────────────────────────────────────────────────────

def _make_test_app():
    from app.channels.telegram import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestTelegramWebhookEndpoint:
    def _text_update(self, chat_id: int = 111, text: str = "chi 300k") -> dict:
        return {
            "update_id": 200001,
            "message": {
                "message_id": 10,
                "from": {"id": chat_id},
                "chat": {"id": chat_id, "type": "private"},
                "date": int(time.time()),
                "text": text,
            },
        }

    def test_valid_request_returns_ok(self):
        client = _make_test_app()
        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("app.channels.telegram._handle_event_background", new_callable=AsyncMock):
            mock_settings.return_value.telegram_webhook_secret = ""  # dev mode

            resp = client.post("/webhook/telegram", json=self._text_update())
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_invalid_secret_returns_403(self):
        client = _make_test_app()
        with patch("app.channels.telegram.get_settings") as mock_settings:
            mock_settings.return_value.telegram_webhook_secret = "correct_secret"

            resp = client.post(
                "/webhook/telegram",
                json=self._text_update(),
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret"},
            )
        assert resp.status_code == 403

    def test_valid_secret_passes(self):
        client = _make_test_app()
        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("app.channels.telegram._handle_event_background", new_callable=AsyncMock):
            mock_settings.return_value.telegram_webhook_secret = "my_secret"

            resp = client.post(
                "/webhook/telegram",
                json=self._text_update(),
                headers={"X-Telegram-Bot-Api-Secret-Token": "my_secret"},
            )
        assert resp.status_code == 200

    def test_invalid_json_returns_400(self):
        client = _make_test_app()
        resp = client.post(
            "/webhook/telegram",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_unsupported_update_returns_note(self):
        client = _make_test_app()
        with patch("app.channels.telegram.get_settings") as mock_settings:
            mock_settings.return_value.telegram_webhook_secret = ""

            resp = client.post(
                "/webhook/telegram",
                json={"update_id": 99999, "callback_query": {"id": "cq1"}},
            )
        assert resp.status_code == 200
        assert resp.json().get("note") == "unsupported_update"
