# Transaction Patterns — Code mẫu chuẩn

## Pattern 1: Commit Expense bình thường (quỹ đủ)

```python
async def commit_expense(
    pending: PendingExpense,
    ctx: RequestContext,
    db: Database,
) -> Expense:
    """Commit expense khi quỹ đủ. Fund giảm X."""
    async with db.transaction():
        # Guard: kiểm tra fund vẫn đủ (race condition)
        fund = await compute_fund_balance(ctx.trip_id, db)
        if fund < pending.amount_vnd:
            raise FundInsufficientError(fund, pending.amount_vnd)

        expense = Expense(
            id=generate_expense_id(),
            trip_id=ctx.trip_id,
            payer_id=pending.payer_id,
            amount_vnd=pending.amount_vnd,
            description=pending.description,
            category=pending.category,
            split_member_ids=pending.split_member_ids,
            source=pending.source,
            occurred_at=pending.occurred_at,
            created_at=utcnow(),
            confirmed_at=utcnow(),
            confirmed_by=pending.payer_id,
            source_event_id=ctx.event_id,
            trace_id=ctx.trace_id,
        )
        await db.insert_expense(expense)

        await db.insert_audit_log(AuditLog(
            action="expense.committed",
            trip_id=ctx.trip_id,
            entity_id=expense.id,
            actor_id=pending.payer_id,
            trace_id=ctx.trace_id,
            details={"amount": pending.amount_vnd, "fund_before": fund},
        ))

        await db.insert_sheet_outbox(SheetOutbox(
            trip_id=ctx.trip_id,
            op="append_expense",
            payload=expense.model_dump_json(),
        ))

        # LUÔN assert sau commit
        fund_after = await compute_fund_balance(ctx.trip_id, db)
        assert fund_after >= 0

        return expense
```

## Pattern 2: Commit Advance Expense (Flow D — ứng tiền)

```python
async def commit_advance_expense(
    pending: PendingAdvanceExpense,
    ctx: RequestContext,
    db: Database,
) -> tuple[Expense, Contribution]:
    """
    Commit 'ứng X để chi Y': 1 expense + 1 contribution(advance) linked.
    Fund không thay đổi.
    """
    async with db.transaction():
        fund_before = await compute_fund_balance(ctx.trip_id, db)

        expense = Expense(
            id=generate_expense_id(),
            trip_id=ctx.trip_id,
            payer_id=pending.payer_id,
            amount_vnd=pending.amount_vnd,
            # ... other fields
        )
        await db.insert_expense(expense)

        # Contribution LUÔN linked với expense vừa tạo
        contribution = Contribution(
            id=generate_contribution_id(),
            trip_id=ctx.trip_id,
            member_id=pending.payer_id,
            amount_vnd=pending.amount_vnd,
            kind=ContributionKind.ADVANCE,
            linked_expense_id=expense.id,  # ← BẮT BUỘC
            note=f"Ứng để chi: {pending.description}",
            occurred_at=pending.occurred_at,
            created_at=utcnow(),
        )
        await db.insert_contribution(contribution)

        await db.insert_audit_log(AuditLog(
            action="advance_expense.committed",
            trip_id=ctx.trip_id,
            entity_id=expense.id,
            trace_id=ctx.trace_id,
        ))
        await db.insert_sheet_outbox(SheetOutbox(
            trip_id=ctx.trip_id,
            op="append_advance_pair",
            payload={"expense_id": expense.id, "contribution_id": contribution.id},
        ))

        # Fund phải bằng với trước (advance không đổi quỹ)
        fund_after = await compute_fund_balance(ctx.trip_id, db)
        assert fund_after == fund_before, \
            f"Advance changed fund: {fund_before} → {fund_after}"
        assert fund_after >= 0

        return expense, contribution
```

## Pattern 3: Commit Auto-advance (Flow C — quỹ không đủ)

```python
async def commit_auto_advance_expense(
    pending: PendingExpense,
    deficit: int,
    ctx: RequestContext,
    db: Database,
) -> tuple[Expense, Contribution]:
    """
    Quỹ thiếu `deficit`. Bot tự ghi contribution(auto_advance) cho payer.
    Fund không thay đổi (advance cancel out với expense linked).
    """
    async with db.transaction():
        fund_before = await compute_fund_balance(ctx.trip_id, db)
        assert deficit > 0, "call this only when deficit > 0"
        assert deficit == pending.amount_vnd - fund_before

        expense = Expense(id=generate_expense_id(), ...)
        await db.insert_expense(expense)

        auto_contribution = Contribution(
            id=generate_contribution_id(),
            trip_id=ctx.trip_id,
            member_id=pending.payer_id,
            amount_vnd=deficit,              # ← CHỈ phần thiếu, không phải toàn bộ
            kind=ContributionKind.AUTO_ADVANCE,
            linked_expense_id=expense.id,   # ← BẮT BUỘC
            note=f"Ứng tự động cho {expense.id}",
        )
        await db.insert_contribution(auto_contribution)

        await db.insert_audit_log(...)
        await db.insert_sheet_outbox(...)

        fund_after = await compute_fund_balance(ctx.trip_id, db)
        # Fund trước: fund_before (có thể > 0 nếu quỹ còn một phần)
        # Sau: fund_before + deficit(auto_contrib) - expense = 0 (hoặc fund_before nếu toàn bộ covered)
        assert fund_after >= 0
        assert fund_after == 0 or fund_after == fund_before - (pending.amount_vnd - deficit)

        return expense, auto_contribution
```

## Idempotency Pattern — chống Zalo retry

```python
async def handle_with_idempotency(event_id: str, handler, db):
    """Wrapper chống duplicate khi Zalo retry webhook."""
    # Check processed_events trước khi làm bất cứ gì
    already_processed = await db.fetch_one(
        "SELECT event_id FROM processed_events WHERE event_id = ?",
        (event_id,)
    )
    if already_processed:
        log.info("event.duplicate_skipped", event_id=event_id)
        return  # Silently skip — đã xử lý rồi

    result = await handler()

    # Mark as processed SAU khi handler thành công
    await db.execute(
        "INSERT INTO processed_events (event_id, processed_at) VALUES (?, ?)",
        (event_id, utcnow())
    )
    return result
```

## Cleanup Pattern — processed_events TTL

```python
# Chạy trong cron hoặc startup
async def cleanup_old_events(db, days: int = 90):
    cutoff = utcnow() - timedelta(days=days)
    await db.execute(
        "DELETE FROM processed_events WHERE processed_at < ?",
        (cutoff,)
    )
```
