"""Commit node: ghi ứng tiền + chi tiêu (advance expense) sau khi user xác nhận."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from app.domain.fund import compute_fund_balance, verify_fund_invariants
from app.domain.models import Contribution, ContributionKind, Expense, ExpenseCategory, ExpenseSource
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


async def commit_advance_expense(ctx: "RequestContext", pending: dict) -> str:
    """
    Ghi advance contribution + expense cùng lúc (Flow D).
    Advance được link trực tiếp với expense → fund không thay đổi.
    """
    payload = json.loads(pending["payload_json"]) if isinstance(pending["payload_json"], str) else pending["payload_json"]

    db = get_db()
    trip_id = ctx.trip_id

    expense_repo = ExpenseRepository(db)
    contrib_repo = ContributionRepository(db)
    audit_repo = AuditLogRepository(db)
    outbox_repo = SheetOutboxRepository(db)
    pending_repo = PendingRepository(db)
    conv_repo = ConversationRepository(db)

    now = datetime.utcnow()
    expense_id = str(uuid.uuid4())
    advance_id = str(uuid.uuid4())

    expense = Expense(
        id=expense_id,
        trip_id=trip_id,
        payer_id=payload["payer_id"],
        amount_vnd=payload["amount_vnd"],
        category=ExpenseCategory(payload["category"]),
        description=payload["description"],
        split_method="equal",
        split_member_ids=payload["split_member_ids"],
        source=ExpenseSource.TEXT,
        source_raw=payload.get("source_raw"),
        occurred_at=datetime.fromisoformat(payload["occurred_at"]),
        created_at=now,
        confirmed_at=now,
        confirmed_by=ctx.member_id or ctx.zalo_user_id,
        source_event_id=ctx.event_id,
        trace_id=ctx.trace_id,
        status="active",
    )
    await expense_repo.insert(expense)

    advance = Contribution(
        id=advance_id,
        trip_id=trip_id,
        member_id=payload["payer_id"],
        amount_vnd=payload["amount_vnd"],
        kind=ContributionKind.ADVANCE,
        linked_expense_id=expense_id,
        note=f"Ứng: {payload['description'][:50]}",
        occurred_at=datetime.fromisoformat(payload["occurred_at"]),
        created_at=now,
        confirmed_at=now,
        source_event_id=ctx.event_id,
        trace_id=ctx.trace_id,
        status="active",
    )
    await contrib_repo.insert(advance)

    await audit_repo.insert(
        action="advance_expense_committed",
        trip_id=trip_id,
        actor_id=ctx.member_id,
        entity_id=expense_id,
        details={
            "amount_vnd": payload["amount_vnd"],
            "description": payload["description"],
            "advance_id": advance_id,
        },
        trace_id=ctx.trace_id,
    )

    await outbox_repo.insert(
        trip_id=trip_id,
        op="add_advance_expense",
        payload={
            "expense_id": expense_id,
            "advance_id": advance_id,
            "amount_vnd": payload["amount_vnd"],
            "description": payload["description"],
            "payer_id": payload["payer_id"],
            "payer_display_name": payload["payer_display_name"],
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
        await expense_repo.cancel(trip_id, expense_id)
        await contrib_repo.cancel(trip_id, advance_id)
        log.error("commit_advance_expense.invariant_violated", violations=[v.name for v in violations])
        raise RuntimeError(f"Fund invariant violated: {violations[0].name}")

    await pending_repo.confirm(ctx.pending_id)
    await conv_repo.set_state(ctx.zalo_user_id, "idle", None)

    fund_after = compute_fund_balance(all_contribs, all_expenses)
    n_split = len(payload["split_member_ids"])

    return (
        f"✅ Đã ghi ứng tiền + chi tiêu:\n"
        f"💰 {format_money(payload['amount_vnd'])} — {payload['description']}\n"
        f"👤 Người ứng: {payload['payer_display_name']} (tiền túi)\n"
        f"👥 Chia cho {n_split} người\n"
        f"💳 Quỹ không đổi: {format_money(fund_after)}"
    )
