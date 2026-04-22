"""Commit node: tạo trip mới + add members."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from app.domain.models import Member, Trip, TripStatus
from app.storage.db import get_db
from app.storage.repositories import (
    AuditLogRepository,
    ConversationRepository,
    MemberRepository,
    PendingRepository,
    SheetOutboxRepository,
    TripRepository,
)
from app.tools.sheet_provisioner import provision_trip_sheet

if TYPE_CHECKING:
    from app.agent.orchestrator import RequestContext

log = structlog.get_logger()


async def commit_trip(ctx: "RequestContext", pending: dict) -> str:
    """
    Tạo trip + add members vào DB.
    Provision Google Sheet (stub Phase 1).
    Set trip status = collecting_topup.
    """
    payload = json.loads(pending["payload_json"]) if isinstance(pending["payload_json"], str) else pending["payload_json"]

    db = get_db()
    trip_repo = TripRepository(db)
    member_repo = MemberRepository(db)
    audit_repo = AuditLogRepository(db)
    outbox_repo = SheetOutboxRepository(db)
    pending_repo = PendingRepository(db)
    conv_repo = ConversationRepository(db)

    now = datetime.utcnow()
    trip_id = f"TRIP-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    # Provision sheet (stub Phase 1 → returns None, None)
    sheet_id, sheet_url = await provision_trip_sheet(
        trip_name=payload["name"],
        trip_id=trip_id,
    )

    trip = Trip(
        id=trip_id,
        name=payload["name"],
        start_date=datetime.fromisoformat(payload["start_date"]),
        end_date=datetime.fromisoformat(payload["end_date"]) if payload.get("end_date") else None,
        status=TripStatus.COLLECTING_TOPUP,
        expected_member_count=payload["expected_member_count"],
        initial_topup_per_member=payload["initial_topup_per_member"],
        sheet_id=sheet_id,
        sheet_url=sheet_url,
        created_by=ctx.member_id,
        created_at=now,
    )
    await trip_repo.insert(trip)

    # Add/create members
    new_members: list[str] = []
    existing_members: list[str] = []

    for rm in payload["resolved_members"]:
        if rm.get("is_new"):
            # Tạo placeholder member
            member_id = str(uuid.uuid4())
            placeholder = Member(
                id=member_id,
                zalo_user_id=None,
                display_name=rm["name"],
                is_admin=False,
                active=True,
                created_at=now,
            )
            await member_repo.insert(placeholder)
            await trip_repo.add_member(trip_id, member_id)
            new_members.append(rm["name"])
        else:
            mid = rm["member_id"]
            await trip_repo.add_member(trip_id, mid)
            existing_members.append(rm["name"])

    # Đảm bảo admin (ctx.member_id) là member
    if ctx.member_id:
        is_already = await trip_repo.is_member(trip_id, ctx.member_id)
        if not is_already:
            await trip_repo.add_member(trip_id, ctx.member_id)

    # Set active trip cho user
    await conv_repo.set_active_trip(ctx.zalo_user_id, trip_id)

    await audit_repo.insert(
        action="trip_created",
        trip_id=trip_id,
        actor_id=ctx.member_id,
        entity_id=trip_id,
        details={
            "name": payload["name"],
            "expected_member_count": payload["expected_member_count"],
            "initial_topup_per_member": payload["initial_topup_per_member"],
        },
        trace_id=ctx.trace_id,
    )

    await outbox_repo.insert(
        trip_id=trip_id,
        op="init_trip_sheet",
        payload={"trip_id": trip_id, "name": payload["name"]},
    )

    await pending_repo.confirm(ctx.pending_id)
    await conv_repo.set_state(ctx.zalo_user_id, "idle", None)

    from app.utils.money import format_money
    topup = payload["initial_topup_per_member"]
    total_expected = topup * payload["expected_member_count"]

    lines = [
        f"✅ Đã tạo chuyến: {payload['name']}",
        f"📅 {payload.get('start_date', '')[:10]}",
        f"👥 {payload['expected_member_count']} thành viên",
        f"💰 Nạp đầu: {format_money(topup)}/người",
        f"💳 Quỹ dự kiến: {format_money(total_expected)}",
        f"🔖 Trạng thái: Đang thu quỹ",
        "",
        "📌 Các thành viên nhắn bot:",
        f'   "<tên> đã nạp {format_money(topup)}"',
    ]
    if new_members:
        lines.append(f"✨ Mới: {', '.join(new_members)}")
    if existing_members:
        lines.append(f"♻️ Đã có: {', '.join(existing_members)}")
    if sheet_url:
        lines.append(f"📊 Sheet: {sheet_url}")

    return "\n".join(lines)
