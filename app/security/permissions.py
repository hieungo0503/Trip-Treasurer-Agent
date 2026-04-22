"""
Permission decorators và helpers.

@require_admin  — chỉ admin_member_ids mới được gọi
@require_trip_member — phải là member của trip trong context
"""

from __future__ import annotations

import functools
from typing import Callable

import structlog

log = structlog.get_logger()


async def _reply(send_fn: Callable, zalo_user_id: str, msg: str) -> None:
    try:
        await send_fn(zalo_user_id, msg)
    except Exception:
        log.warning("permission.reply_failed", user=zalo_user_id)


def require_admin(handler: Callable) -> Callable:
    """
    Decorator: reject nếu ctx.member_id không nằm trong settings.admin_member_id_list.
    Handler phải nhận (ctx, ...) với ctx có attribute member_id và send_fn.
    """
    @functools.wraps(handler)
    async def wrapper(ctx, *args, **kwargs):
        from app.config import get_settings
        settings = get_settings()
        if ctx.member_id not in settings.admin_member_id_list:
            log.warning(
                "permission.admin_required",
                member_id=ctx.member_id,
                handler=handler.__name__,
            )
            await ctx.reply("⛔ Lệnh này chỉ dành cho admin.")
            return None
        return await handler(ctx, *args, **kwargs)

    return wrapper


def require_trip_member(handler: Callable) -> Callable:
    """
    Decorator: reject nếu ctx.member_id không phải member của ctx.trip_id.
    """
    @functools.wraps(handler)
    async def wrapper(ctx, *args, **kwargs):
        if not ctx.trip_id:
            await ctx.reply("⚠️ Không có chuyến đi đang hoạt động. Gõ /help để xem hướng dẫn.")
            return None
        # Kiểm tra membership — repo phải được inject vào ctx hoặc qua db
        from app.storage.db import get_db
        from app.storage.repositories import TripRepository
        repo = TripRepository(get_db())
        is_member = await repo.is_member(ctx.trip_id, ctx.member_id)
        if not is_member:
            log.warning(
                "permission.not_trip_member",
                member_id=ctx.member_id,
                trip_id=ctx.trip_id,
            )
            await ctx.reply("⛔ Bạn không phải thành viên của chuyến này.")
            return None
        return await handler(ctx, *args, **kwargs)

    return wrapper
