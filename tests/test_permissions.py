"""
Tests cho app/security/permissions.py

@require_admin — reject nếu không phải admin
@require_trip_member — reject nếu không phải member của trip
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_ctx(member_id: str = "M001", trip_id: str | None = "TRIP-001") -> MagicMock:
    ctx = MagicMock()
    ctx.member_id = member_id
    ctx.trip_id = trip_id
    ctx.reply = AsyncMock()
    return ctx


# ── require_admin ─────────────────────────────────────────────────────────────

class TestRequireAdmin:
    async def test_admin_passes(self):
        from app.security.permissions import require_admin

        @require_admin
        async def handler(ctx):
            return "ok"

        ctx = _make_ctx(member_id="ADMIN1")
        with patch.dict(os.environ, {"ADMIN_MEMBER_IDS": "ADMIN1"}):
            from app.config import get_settings
            get_settings.cache_clear()
            result = await handler(ctx)

        assert result == "ok"
        ctx.reply.assert_not_called()

    async def test_non_admin_blocked(self):
        from app.security.permissions import require_admin

        called = False

        @require_admin
        async def handler(ctx):
            nonlocal called
            called = True
            return "ok"

        ctx = _make_ctx(member_id="NOT_ADMIN")
        with patch.dict(os.environ, {"ADMIN_MEMBER_IDS": "ADMIN1"}):
            from app.config import get_settings
            get_settings.cache_clear()
            result = await handler(ctx)

        assert result is None
        assert not called
        ctx.reply.assert_awaited_once()
        assert "admin" in ctx.reply.call_args[0][0].lower()

    async def test_admin_in_list(self):
        """ADMIN_MEMBER_IDS có thể là comma-separated list."""
        from app.security.permissions import require_admin

        @require_admin
        async def handler(ctx):
            return "ok"

        ctx = _make_ctx(member_id="M002")
        with patch.dict(os.environ, {"ADMIN_MEMBER_IDS": "M001,M002,M003"}):
            from app.config import get_settings
            get_settings.cache_clear()
            result = await handler(ctx)

        assert result == "ok"

    async def test_handler_args_passed_through(self):
        """Decorator phải forward args/kwargs cho handler."""
        from app.security.permissions import require_admin

        @require_admin
        async def handler(ctx, x, y=10):
            return x + y

        ctx = _make_ctx(member_id="ADMIN1")
        with patch.dict(os.environ, {"ADMIN_MEMBER_IDS": "ADMIN1"}):
            from app.config import get_settings
            get_settings.cache_clear()
            result = await handler(ctx, 5, y=3)

        assert result == 8

    async def test_non_admin_gets_reply(self):
        """Non-admin nhận reply từ ctx.reply trực tiếp."""
        from app.security.permissions import require_admin

        @require_admin
        async def handler(ctx):
            return "ok"

        ctx = _make_ctx(member_id="NOT_ADMIN")

        with patch.dict(os.environ, {"ADMIN_MEMBER_IDS": "ADMIN1"}):
            from app.config import get_settings
            get_settings.cache_clear()
            result = await handler(ctx)

        assert result is None
        ctx.reply.assert_awaited_once()

    async def test_functools_wraps_preserved(self):
        """require_admin phải giữ __name__ của handler gốc."""
        from app.security.permissions import require_admin

        @require_admin
        async def my_special_handler(ctx):
            return "ok"

        assert my_special_handler.__name__ == "my_special_handler"


# ── _reply helper ─────────────────────────────────────────────────────────────

class TestReplyHelper:
    async def test_reply_sends_message(self):
        from app.security.permissions import _reply

        send_fn = AsyncMock()
        await _reply(send_fn, "USER1", "hello")
        send_fn.assert_awaited_once_with("USER1", "hello")

    async def test_reply_handles_exception(self):
        from app.security.permissions import _reply

        send_fn = AsyncMock(side_effect=Exception("network error"))
        # Không nên raise
        await _reply(send_fn, "USER1", "hello")


# ── require_trip_member ───────────────────────────────────────────────────────

class TestRequireTripMember:
    async def test_no_trip_blocked(self):
        from app.security.permissions import require_trip_member

        @require_trip_member
        async def handler(ctx):
            return "ok"

        ctx = _make_ctx(trip_id=None)
        result = await handler(ctx)

        assert result is None
        ctx.reply.assert_awaited_once()
        msg = ctx.reply.call_args[0][0]
        assert "chuyến" in msg.lower() or "trip" in msg.lower()

    async def test_member_of_trip_passes(self):
        from app.security.permissions import require_trip_member

        @require_trip_member
        async def handler(ctx):
            return "passed"

        ctx = _make_ctx(member_id="M001", trip_id="TRIP-001")

        mock_repo = AsyncMock()
        mock_repo.is_member = AsyncMock(return_value=True)

        with patch("app.storage.db.get_db"), \
             patch("app.storage.repositories.TripRepository", return_value=mock_repo):
            result = await handler(ctx)

        assert result == "passed"
        ctx.reply.assert_not_called()

    async def test_non_member_blocked(self):
        from app.security.permissions import require_trip_member

        called = False

        @require_trip_member
        async def handler(ctx):
            nonlocal called
            called = True
            return "ok"

        ctx = _make_ctx(member_id="M999", trip_id="TRIP-001")

        mock_repo = AsyncMock()
        mock_repo.is_member = AsyncMock(return_value=False)

        with patch("app.storage.db.get_db"), \
             patch("app.storage.repositories.TripRepository", return_value=mock_repo):
            result = await handler(ctx)

        assert result is None
        assert not called
        ctx.reply.assert_awaited_once()
        msg = ctx.reply.call_args[0][0]
        assert "thành viên" in msg.lower() or "member" in msg.lower()

    async def test_functools_wraps_preserved(self):
        from app.security.permissions import require_trip_member

        @require_trip_member
        async def my_handler(ctx):
            return "ok"

        assert my_handler.__name__ == "my_handler"
