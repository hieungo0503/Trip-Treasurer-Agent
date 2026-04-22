"""Commit node: ghi topup (nạp quỹ) sau khi user xác nhận."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from app.domain.fund import compute_fund_balance, verify_fund_invariants
from app.domain.models import Contribution, ContributionKind
from app.storage.db import get_db
from app.storage.repositories import (
    AuditLogRepository,
    ContributionRepository,
    ConversationRepository,
    ExpenseRepository,
    MemberRepository,
    PendingRepository,
    SheetOutboxRepository,
    TripRepository,
)
from app.utils.money import format_money

if TYPE_CHECKING:
    from app.agent.orchestrator import RequestContext

log = structlog.get_logger()


async def commit_topup(ctx: "RequestContext", pending: dict) -> str:
    """Ghi extra_topup contribution vào DB."""
    payload = json.loads(pending["payload_json"]) if isinstance(pending["payload_json"], str) else pending["payload_json"]

    db = get_db()
    trip_id = ctx.trip_id

    contrib_repo = ContributionRepository(db)
    expense_repo = ExpenseRepository(db)
    audit_repo = AuditLogRepository(db)
    outbox_repo = SheetOutboxRepository(db)
    pending_repo = PendingRepository(db)
    conv_repo = ConversationRepository(db)

    now = datetime.utcnow()
    contrib_id = str(uuid.uuid4())
    kind = ContributionKind(payload.get("kind", "extra_topup"))

    contrib = Contribution(
        id=contrib_id,
        trip_id=trip_id,
        member_id=payload["member_id"],
        amount_vnd=payload["amount_vnd"],
        kind=kind,
        linked_expense_id=None,
        note=payload.get("note"),
        occurred_at=datetime.fromisoformat(payload["occurred_at"]),
        created_at=now,
        confirmed_at=now,
        source_event_id=ctx.event_id,
        trace_id=ctx.trace_id,
        status="active",
    )
    await contrib_repo.insert(contrib)

    await audit_repo.insert(
        action="topup_committed",
        trip_id=trip_id,
        actor_id=ctx.member_id,
        entity_id=contrib_id,
        details={"amount_vnd": payload["amount_vnd"], "kind": kind.value},
        trace_id=ctx.trace_id,
    )

    await outbox_repo.insert(
        trip_id=trip_id,
        op="add_contribution",
        payload={
            "contrib_id": contrib_id,
            "amount_vnd": payload["amount_vnd"],
            "kind": kind.value,
            "member_id": payload["member_id"],
            "member_display_name": payload["member_display_name"],
        },
    )

    all_expenses = await expense_repo.list_active(trip_id)
    all_contribs = await contrib_repo.list_active(trip_id)

    trip_repo = TripRepository(db)
    member_ids = await trip_repo.get_member_ids(trip_id)
    member_repo = MemberRepository(db)
    members = []
    for mid in member_ids:
        m = await member_repo.get_by_id(mid)
        if m:
            members.append((m.id, m.display_name))

    violations = verify_fund_invariants(members, all_contribs, all_expenses)
    if violations:
        await contrib_repo.cancel(trip_id, contrib_id)
        log.error("commit_topup.invariant_violated", violations=[v.name for v in violations])
        raise RuntimeError(f"Fund invariant violated: {violations[0].name}")

    await pending_repo.confirm(ctx.pending_id)
    await conv_repo.set_state(ctx.zalo_user_id, "idle", None)

    fund_after = compute_fund_balance(all_contribs, all_expenses)

    return (
        f"✅ Đã ghi nạp quỹ:\n"
        f"💰 {format_money(payload['amount_vnd'])} — {payload['member_display_name']}\n"
        f"💳 Quỹ hiện tại: {format_money(fund_after)}"
    )
