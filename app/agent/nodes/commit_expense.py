"""Commit node: ghi expense sau khi user xác nhận."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from app.domain.fund import check_expense_against_fund, compute_fund_balance, verify_fund_invariants
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


async def commit_expense(ctx: "RequestContext", pending: dict) -> str:
    """
    Ghi expense vào DB.
    Nếu quỹ không đủ tại thời điểm commit (state có thể thay đổi), tự tạo auto_advance.
    Rollback bằng cách cancel record nếu invariant bị vi phạm.
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

    # Re-check fund tại thời điểm commit (state có thể thay đổi giữa parse và confirm)
    expenses = await expense_repo.list_active(trip_id)
    contribs = await contrib_repo.list_active(trip_id)
    check = check_expense_against_fund(payload["amount_vnd"], contribs, expenses)

    now = datetime.utcnow()
    expense_id = str(uuid.uuid4())

    expense = Expense(
        id=expense_id,
        trip_id=trip_id,
        payer_id=payload["payer_id"],
        amount_vnd=payload["amount_vnd"],
        category=ExpenseCategory(payload["category"]),
        description=payload["description"],
        split_method="equal",
        split_member_ids=payload["split_member_ids"],
        source=ExpenseSource(payload.get("source", "text")),
        source_raw=payload.get("source_raw"),
        occurred_at=datetime.fromisoformat(payload["occurred_at"]),
        created_at=now,
        confirmed_at=now,
        confirmed_by=ctx.zalo_user_id,
        source_event_id=ctx.event_id,
        trace_id=ctx.trace_id,
        status="active",
    )
    await expense_repo.insert(expense)

    advance_id: str | None = None
    if not check.can_pay_from_fund and check.deficit > 0:
        advance_id = str(uuid.uuid4())
        advance = Contribution(
            id=advance_id,
            trip_id=trip_id,
            member_id=payload["payer_id"],
            amount_vnd=check.deficit,
            kind=ContributionKind.AUTO_ADVANCE,
            linked_expense_id=expense_id,
            note=f"Auto-advance: {payload['description'][:50]}",
            occurred_at=now,
            created_at=now,
            confirmed_at=now,
            source_event_id=ctx.event_id,
            trace_id=ctx.trace_id,
            status="active",
        )
        await contrib_repo.insert(advance)

    await audit_repo.insert(
        action="expense_committed",
        trip_id=trip_id,
        actor_id=ctx.member_id,
        entity_id=expense_id,
        details={
            "amount_vnd": payload["amount_vnd"],
            "description": payload["description"],
            "auto_advance": advance_id is not None,
            "advance_id": advance_id,
        },
        trace_id=ctx.trace_id,
    )

    await outbox_repo.insert(
        trip_id=trip_id,
        op="add_expense",
        payload={
            "expense_id": expense_id,
            "amount_vnd": payload["amount_vnd"],
            "description": payload["description"],
            "category": payload["category"],
            "payer_id": payload["payer_id"],
            "payer_display_name": payload["payer_display_name"],
            "occurred_at": payload["occurred_at"],
        },
    )

    # Verify invariants — rollback bằng cancel nếu fail
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
        if advance_id:
            await contrib_repo.cancel(trip_id, advance_id)
        log.error("commit_expense.invariant_violated", violations=[v.name for v in violations])
        raise RuntimeError(f"Fund invariant violated: {violations[0].name}")

    await pending_repo.confirm(ctx.pending_id)
    await conv_repo.set_state(ctx.zalo_user_id, "idle", None)

    fund_after = compute_fund_balance(all_contribs, all_expenses)
    n_split = len(payload["split_member_ids"])

    lines = [
        "✅ Đã ghi chi tiêu:",
        f"💰 {format_money(payload['amount_vnd'])} — {payload['description']}",
        f"👤 Người chi: {payload['payer_display_name']}",
        f"👥 Chia cho {n_split} người",
        f"💳 Quỹ còn lại: {format_money(fund_after)}",
    ]
    if advance_id:
        lines.append(
            f"⚠️ Quỹ không đủ — đã ghi ứng {format_money(check.deficit)} cho {payload['payer_display_name']}"
        )
    return "\n".join(lines)
