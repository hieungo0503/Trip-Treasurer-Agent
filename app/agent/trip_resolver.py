"""
Trip context resolver — xử lý khi user có nhiều active trip.

MVP rule: user chỉ có tối đa 1 active trip cùng lúc.
Module này chuẩn bị sẵn logic cho Phase 4 (multi-active-trip).
"""

from __future__ import annotations

from typing import Optional

import structlog

from app.domain.models import Trip, TripStatus
from app.storage.db import get_db
from app.storage.repositories import ConversationRepository, TripRepository

log = structlog.get_logger()


async def resolve_active_trip(
    member_id: str,
    zalo_user_id: str,
    stored_trip_id: Optional[str],
) -> Optional[Trip]:
    """
    Tìm trip đang active cho member.

    Logic:
    1. Nếu stored_trip_id hợp lệ (active, member là thành viên) → dùng
    2. Nếu không → tìm tất cả active trips của member
       - 0 trips → None
       - 1 trip  → auto-select, lưu vào conversation
       - 2+ trips → trả về None (caller xử lý multi-trip prompt)
    """
    db = get_db()
    trip_repo = TripRepository(db)
    conv_repo = ConversationRepository(db)

    if stored_trip_id:
        trip = await trip_repo.get_by_id(stored_trip_id)
        if (
            trip
            and trip.status in (TripStatus.ACTIVE, TripStatus.COLLECTING_TOPUP)
            and await trip_repo.is_member(stored_trip_id, member_id)
        ):
            return trip
        # Stored trip không còn valid → clear
        await conv_repo.set_active_trip(zalo_user_id, None)

    active_trips = await trip_repo.get_active_trips_for_member(member_id)

    # Cũng lấy collecting_topup trips
    all_trips = await trip_repo.get_all_trips_for_member(member_id)
    collecting = [
        t for t in all_trips
        if t.status == TripStatus.COLLECTING_TOPUP
        and t not in active_trips
    ]
    candidates = active_trips + collecting

    if len(candidates) == 1:
        await conv_repo.set_active_trip(zalo_user_id, candidates[0].id)
        return candidates[0]

    return None


def build_multi_trip_prompt(trips: list[Trip]) -> str:
    """Card hỏi user chọn trip khi có nhiều active trips."""
    lines = [
        "⚠️ Bạn đang có nhiều chuyến:",
        "",
    ]
    for i, t in enumerate(trips, 1):
        lines.append(f"   {i}. [{t.id}] {t.name} ({t.status.value})")
    lines += [
        "",
        "Gõ /trip_switch <ID> để chọn chuyến.",
        "VD: /trip_switch TRIP-20260510",
    ]
    return "\n".join(lines)
