# Contribution Kinds — Edge Cases và Quyết định thiết kế

## Tại sao có 4 kinds, không phải 2?

**initial_topup vs extra_topup**: Tách ra để biết ai đã nạp đầu chuyến hay chưa.
Trip ở state COLLECTING_TOPUP chỉ nhận initial_topup. Cần phân biệt để:
- Track tiến độ "3/4 người đã nạp đầu"
- Không cho phép ghi expense trước khi trip ACTIVE

**advance vs auto_advance**: Khác nguồn gốc (chủ động vs bị động) nhưng giống accounting.
Tách ra để:
- User hiểu `/nap_cua_toi`: "đây là bạn chủ động ứng" vs "đây là bot tự ghi"
- `/huy_auto` chỉ cho hủy `auto_advance`, không cho hủy `advance` (bạn chủ động ứng thì không thể tự hủy)
- Audit trail rõ ràng hơn

## linked_expense_id — khi nào bắt buộc

| kind | linked_expense_id | Nếu NULL thì |
|---|---|---|
| initial_topup | NULL | OK — nạp vào quỹ, chưa linked gì |
| extra_topup | NULL | OK — nạp thêm vào quỹ |
| advance | PHẢI có | BUG — advance mà không biết chi cho expense nào |
| auto_advance | PHẢI có | BUG — auto_advance mà không biết expense nào trigger |

Invariant kiểm tra trong `verify_fund_invariants()`:
```python
for c in contributions:
    if c.kind in (ADVANCE, AUTO_ADVANCE) and c.linked_expense_id is None:
        violations.append("advance_missing_link")
    if c.kind in (INITIAL_TOPUP, EXTRA_TOPUP) and c.linked_expense_id is not None:
        violations.append("topup_has_unexpected_link")
```

## Soft delete — STATUS = 'cancelled'

Không bao giờ DELETE record khỏi DB. Chỉ soft delete:

```python
# Hủy expense
await db.execute(
    "UPDATE expenses SET status='cancelled' WHERE id=?",
    (expense_id,)
)

# Nếu expense có linked auto_advance → cũng cancel contribution đó
await db.execute(
    "UPDATE contributions SET status='cancelled' WHERE linked_expense_id=? AND kind='auto_advance'",
    (expense_id,)
)
```

Lý do giữ soft delete:
- Audit trail đầy đủ
- Có thể restore nếu cần
- Không break foreign key

## /huy_auto — cancel auto_advance của 1 expense

User gõ `/huy_auto EXP-xxx` khi lỡ confirm auto-advance nhưng thực ra đã ứng thủ công.

```python
async def handle_huy_auto(expense_id: str, actor_id: str, db: Database):
    # 1. Tìm contribution auto_advance linked với expense này
    auto = await db.fetch_one(
        "SELECT * FROM contributions WHERE linked_expense_id=? AND kind='auto_advance' AND status='active'",
        (expense_id,)
    )
    if not auto:
        return reply("Không tìm thấy auto-advance nào cho expense này.")

    # 2. Kiểm tra actor_id là người ứng
    if auto.member_id != actor_id:
        return reply("Bạn chỉ có thể hủy auto-advance của chính mình.")

    # 3. Cancel
    await db.execute("UPDATE contributions SET status='cancelled' WHERE id=?", (auto.id,))
    await db.insert_audit_log(action="auto_advance.cancelled", entity_id=auto.id)

    # 4. Fund sau cancel phải vẫn >= 0 (vì expense vẫn còn, nhưng advance bị hủy)
    # → fund sẽ giảm bằng phần expense không còn được cover bởi advance
    # → user phải gõ "ứng thủ công" thay thế
    fund = await compute_fund_balance(ctx.trip_id, db)
    if fund < 0:
        # Rollback cancel
        await db.execute("UPDATE contributions SET status='active' WHERE id=?", (auto.id,))
        return reply("Không thể hủy: quỹ sẽ âm. Bạn cần nạp thêm trước.")

    reply(f"✅ Đã hủy auto-advance {auto.amount_vnd:,}đ.\n"
          f"Gõ 'ứng {auto.amount_vnd//1000}k' để ghi ứng thủ công thay thế.")
```

## Ứng tiền khi quỹ = 0 chính xác

Nếu quỹ đúng = 0 và user chi X → toàn bộ X là auto_advance:
- deficit = X
- auto_advance.amount_vnd = X (bằng expense.amount_vnd)
- Fund sau: 0 + X (auto_advance không tính) - X (linked, không tính) = 0 ✅

## Nạp dư (overpaid initial_topup)

User nạp 1.2tr khi trip yêu cầu 1tr → chấp nhận, ghi đủ 1.2tr.
Họ sẽ có `net > 0` cao hơn → được hoàn lại nhiều hơn cuối chuyến.
Bot reply: "✅ Đã ghi nạp 1.200.000đ (vượt mức 200.000đ, sẽ được hoàn cuối chuyến)."

## Nạp thiếu (partial initial_topup)

User nạp 500k khi trip yêu cầu 1tr → chấp nhận nhưng đánh dấu chưa đủ.
Bot reply: "✅ Đã ghi nạp 500.000đ. Còn thiếu 500.000đ so với mức yêu cầu.
          Gõ 'nạp 500k' để bổ sung sau."
Không block trip.
