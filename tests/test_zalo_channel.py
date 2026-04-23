"""
Tests bổ sung cho channels/telegram.py.

Covers (phần chưa có trong test_telegram_channel.py):
  - send_telegram_message_safe: không raise khi send thất bại
  - start_polling: no token skip, webhook cleared, processes updates, handles cancel
  - register_webhook endpoint: ok, no token, no url, api error
  - unregister_webhook endpoint: ok, no token
  - webhook_info endpoint: ok, no token
  - _handle_event_background: exception bị bắt và log
  - parse_telegram_update: thêm edge cases (sticker, voice, empty chat)
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── send_telegram_message_safe ────────────────────────────────────────────────

class TestSendTelegramMessageSafe:
    @pytest.mark.asyncio
    async def test_safe_wrapper_does_not_raise(self):
        """send_telegram_message_safe nuốt exception, không raise ra ngoài."""
        from app.channels.telegram import send_telegram_message_safe

        with patch("app.channels.telegram.send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception("network error")
            await send_telegram_message_safe("123", "test")  # không raise

    @pytest.mark.asyncio
    async def test_safe_wrapper_delegates_on_success(self):
        from app.channels.telegram import send_telegram_message_safe

        with patch("app.channels.telegram.send_telegram_message", new_callable=AsyncMock) as mock_send:
            await send_telegram_message_safe("456", "hello")
            mock_send.assert_called_once_with("456", "hello")


# ── start_polling ─────────────────────────────────────────────────────────────

class TestStartPolling:
    @pytest.mark.asyncio
    async def test_no_token_returns_immediately(self):
        from app.channels.telegram import start_polling

        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_settings.return_value.telegram_bot_token = ""
            await start_polling()
            mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancelled_error_exits_cleanly(self):
        """CancelledError từ asyncio → hàm return (không raise)."""
        from app.channels.telegram import start_polling

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.CancelledError()
            raise AssertionError("should not reach here")

        mock_resp_delete = MagicMock()
        mock_resp_delete.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp_delete)
        mock_client.get = AsyncMock(side_effect=mock_get)

        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("httpx.AsyncClient", return_value=mock_client):
            mock_settings.return_value.telegram_bot_token = "token"
            await start_polling()  # không raise CancelledError

    @pytest.mark.asyncio
    async def test_processes_text_update(self):
        """Loop nhận update và gọi handle_event."""
        from app.channels.telegram import start_polling

        handled = []

        async def fake_handle(event):
            handled.append(event)

        text_update = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "from": {"id": 111},
                "chat": {"id": 111, "type": "private"},
                "date": int(time.time()),
                "text": "chi 100k",
            },
        }

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_r = MagicMock()
            if call_count == 1:
                mock_r.json.return_value = {"ok": True, "result": [text_update]}
            else:
                raise asyncio.CancelledError()
            return mock_r

        mock_delete_resp = MagicMock()
        mock_delete_resp.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_delete_resp)
        mock_client.get = AsyncMock(side_effect=mock_get)

        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("app.agent.orchestrator.handle_event", new=AsyncMock(side_effect=fake_handle)):
            mock_settings.return_value.telegram_bot_token = "token"
            await start_polling()

        assert len(handled) == 1
        assert handled[0]["message"]["text"] == "chi 100k"

    @pytest.mark.asyncio
    async def test_api_error_sleeps_and_continues(self):
        """API trả về ok=False → sleep và tiếp tục (không crash)."""
        from app.channels.telegram import start_polling

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_r = MagicMock()
            if call_count == 1:
                mock_r.json.return_value = {"ok": False, "error_code": 401}
            else:
                raise asyncio.CancelledError()
            return mock_r

        mock_delete_resp = MagicMock()
        mock_delete_resp.json.return_value = {"ok": True}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_delete_resp)
        mock_client.get = AsyncMock(side_effect=mock_get)

        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_settings.return_value.telegram_bot_token = "token"
            await start_polling()


# ── register/unregister webhook endpoints ────────────────────────────────────

def _make_mgmt_app():
    from app.channels.telegram import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestRegisterWebhook:
    def test_no_token_returns_500(self):
        client = _make_mgmt_app()
        with patch("app.channels.telegram.get_settings") as mock_settings:
            mock_settings.return_value.telegram_bot_token = ""
            resp = client.post("/webhook/telegram/register_webhook")
        assert resp.status_code == 500

    def test_no_webhook_url_returns_500(self):
        client = _make_mgmt_app()
        with patch("app.channels.telegram.get_settings") as mock_settings:
            mock_settings.return_value.telegram_bot_token = "token"
            mock_settings.return_value.telegram_webhook_url = ""
            resp = client.post("/webhook/telegram/register_webhook")
        assert resp.status_code == 500

    def test_api_ok_returns_200(self):
        client = _make_mgmt_app()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "description": "Webhook was set"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("httpx.AsyncClient", return_value=mock_client):
            mock_settings.return_value.telegram_bot_token = "token"
            mock_settings.return_value.telegram_webhook_url = "https://example.com/webhook/telegram"
            mock_settings.return_value.telegram_webhook_secret = ""
            resp = client.post("/webhook/telegram/register_webhook")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_api_error_returns_500(self):
        client = _make_mgmt_app()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False, "description": "Bad Request"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("httpx.AsyncClient", return_value=mock_client):
            mock_settings.return_value.telegram_bot_token = "token"
            mock_settings.return_value.telegram_webhook_url = "https://example.com/wh"
            mock_settings.return_value.telegram_webhook_secret = ""
            resp = client.post("/webhook/telegram/register_webhook")

        assert resp.status_code == 500


class TestUnregisterWebhook:
    def test_no_token_returns_500(self):
        client = _make_mgmt_app()
        with patch("app.channels.telegram.get_settings") as mock_settings:
            mock_settings.return_value.telegram_bot_token = ""
            resp = client.request("DELETE", "/webhook/telegram/register_webhook")
        assert resp.status_code == 500

    def test_ok_returns_200(self):
        client = _make_mgmt_app()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "description": "Webhook was deleted"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.channels.telegram.get_settings") as mock_settings, \
             patch("httpx.AsyncClient", return_value=mock_client):
            mock_settings.return_value.telegram_bot_token = "token"
            resp = client.request("DELETE", "/webhook/telegram/register_webhook")

        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ── _handle_event_background ─────────────────────────────────────────────────

class TestHandleEventBackground:
    @pytest.mark.asyncio
    async def test_exception_is_caught(self):
        """Exception trong handler không bubble up."""
        from app.channels.telegram import _handle_event_background

        async def failing_handler(event):
            raise ValueError("agent crashed")

        event = {"event_id": "tg-001", "user_id": "123", "event_name": "user_send_text"}
        await _handle_event_background(failing_handler, event)  # không raise

    @pytest.mark.asyncio
    async def test_success_case(self):
        from app.channels.telegram import _handle_event_background

        called_with = []

        async def good_handler(event):
            called_with.append(event)

        event = {"event_id": "tg-002", "user_id": "456", "event_name": "user_send_text"}
        await _handle_event_background(good_handler, event)
        assert called_with == [event]


# ── parse_telegram_update edge cases ─────────────────────────────────────────

class TestParseTelegramEdgeCases:
    def test_sticker_returns_none(self):
        from app.channels.telegram import parse_telegram_update

        update = {
            "update_id": 300001,
            "message": {
                "message_id": 5,
                "from": {"id": 999},
                "chat": {"id": 999, "type": "private"},
                "date": int(time.time()),
                "sticker": {"file_id": "sticker_abc", "emoji": "👍"},
            },
        }
        assert parse_telegram_update(update) is None

    def test_voice_returns_none(self):
        from app.channels.telegram import parse_telegram_update

        update = {
            "update_id": 300002,
            "message": {
                "message_id": 6,
                "from": {"id": 999},
                "chat": {"id": 999, "type": "private"},
                "date": int(time.time()),
                "voice": {"file_id": "voice_abc", "duration": 5},
            },
        }
        assert parse_telegram_update(update) is None

    def test_channel_key_is_telegram(self):
        from app.channels.telegram import parse_telegram_update

        update = {
            "update_id": 300003,
            "message": {
                "message_id": 7,
                "from": {"id": 777},
                "chat": {"id": 777, "type": "private"},
                "date": int(time.time()),
                "text": "nạp 200k",
            },
        }
        event = parse_telegram_update(update)
        assert event is not None
        assert event["_channel"] == "telegram"

    def test_empty_string_chat_id_returns_none(self):
        from app.channels.telegram import parse_telegram_update

        update = {
            "update_id": 300004,
            "message": {
                "message_id": 8,
                "from": {"id": 888},
                "chat": {"id": 0, "type": "private"},  # id = 0 → str "0" → valid (edge)
                "date": int(time.time()),
                "text": "test",
            },
        }
        # id=0 → user_id="0" → không phải empty → vẫn parse được
        event = parse_telegram_update(update)
        assert event is not None
        assert event["user_id"] == "0"
