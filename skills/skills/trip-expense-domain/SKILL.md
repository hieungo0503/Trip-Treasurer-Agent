---
name: trip-expense-domain
description: >
  Core domain logic cho Trip Treasurer Agent — quỹ chung, fund invariants,
  contribution kinds, settlement algorithm, member resolver, fuzzy match.
  PHẢI đọc skill này trước khi: viết/sửa code trong app/domain/, implement
  node commit expense/contribution/advance, debug fund_balance sai, viết test
  cho fund/settlement/member logic, hoặc thêm intent mới liên quan đến tiền.
  Logic quỹ ở đây KHÁC với Splitwise — advance không tăng quỹ thực. Đọc kỹ.
---

# Trip Expense Domain — Core Logic

## 1. Fund Model (ĐỌC KỸ — khác Splitwise)

### Công thức

```
fund_balance = Σ contribution(initial_topup, extra_topup)
             − Σ expense KHÔNG CÓ linked contribution (advance/auto_advance)

contribution_i = Σ mọi contribution của member i (tất cả kind, active)
fair_share_i   = Σ (expense.amount / len(split_member_ids))
                 với expense có member i trong split
net_i          = contribution_i − fair_share_i

INVARIANT: Σ net_i == fund_balance (tolerance ≤ 1đ do integer division)
INVARIANT: fund_balance ≥ 0 luôn luôn — nếu âm là BUG
```

### 4 loại Contribution

| kind | Tăng quỹ thực? | Linked expense? | Khi nào |
|---|---|---|---|
| `initial_topup` | ✅ | ❌ KHÔNG | Nạp đầu chuyến |
| `extra_topup` | ✅ | ❌ KHÔNG | Nạp thêm bất kỳ lúc |
| `advance` | ❌ | ✅ BẮT BUỘC | User chủ động "ứng X để chi Y" |
| `auto_advance` | ❌ | ✅ BẮT BUỘC | Bot tự ghi khi quỹ không đủ |

**Quy tắc vàng:**
- `advance`/`auto_advance` KHÔNG tăng quỹ — chúng cancel out với expense linked
- `fund_balance` tính theo `created_at` (input order), KHÔNG phải `occurred_at`
- `occurred_at` chỉ là metadata hiển thị cho user

Chi tiết + ví dụ số → `references/fund_model.md`

## 2. DB Commit Pattern — KHÔNG bỏ bước nào

```python
async with db.transaction():
    # 1. Check fund trước khi commit
    fund_before = await compute_fund_balance(trip_id, db)
    check = check_expense_against_fund(amount, contribs, expenses)

    # 2. Insert records (expense + contribution nếu cần)
    expense = await db.insert_expense(...)
    if auto_advance:
        contrib = await db.insert_contribution(
            kind=AUTO_ADVANCE, linked_expense_id=expense.id
        )

    # 3. Audit log — LUÔN LUÔN
    await db.insert_audit_log(
        action="expense.committed",
        trip_id=trip_id,
        entity_id=expense.id,
        trace_id=ctx.trace_id,
    )

    # 4. Sheet outbox — async projector sẽ xử lý sau
    await db.insert_sheet_outbox(trip_id=trip_id, op="append_expense")

    # 5. Assert invariant SAU commit — nếu fail → rollback transaction
    fund_after = await compute_fund_balance(trip_id, db)
    assert fund_after >= 0, f"fund_balance went negative after commit: {fund_after}"
    violations = await verify_fund_invariants(trip_id, db)
    assert not violations, f"Invariant violations: {violations}"
```

Chi tiết code pattern → `references/transaction_patterns.md`

## 3. Trip Isolation — KHÔNG BAO GIỜ query thiếu trip_id

```python
# ❌ BAD — cross-trip data leak, bug nghiêm trọng
expenses = await db.fetch_all("SELECT * FROM expenses WHERE status='active'")

# ✅ GOOD — luôn scope theo trip_id
expenses = await db.fetch_all(
    "SELECT * FROM expenses WHERE trip_id = ? AND status = 'active'",
    (ctx.trip_id,)
)
```

Code review rule: mọi query trên `expenses`, `contributions`, `audit_log`, `sheet_outbox` phải có `WHERE trip_id = ?`.

## 4. Intent Matrix — 5 loại, đừng nhầm

| User gõ | Intent | Ghi DB | Δ quỹ thực |
|---|---|---|---|
| "chi/trả X" (quỹ đủ) | `log_expense` | Expense | −X |
| "chi/trả X" (quỹ không đủ) | `log_expense` → auto_advance | Expense + Contribution(auto_advance) | 0 |
| "nạp/góp X" | `log_topup` | Contribution(extra_topup) | +X |
| "ứng X để chi Y" | `log_advance_expense` | Expense + Contribution(advance) | 0 |
| "<tên> đã nạp X" | `log_initial_topup` | Contribution(initial_topup) | +X |

## 5. Settlement Algorithm

Greedy, tối thiểu hóa số giao dịch. Xem `app/domain/settlement.py` đã implement.

Flow:
1. Tính `net_i` cho mỗi member
2. Tách creditors (net > 0) và debtors (net < 0)
3. Greedy: debtors trả cho creditors cho đến khi cân bằng
4. Phân phối `fund_remain` cho creditors qua admin

## 6. Member Resolver

Khi tạo trip mới, resolve tên admin khai → member trong DB:
- 0 match → tạo placeholder (zalo_user_id = NULL)
- 1 match → reuse member cũ
- 2+ match → AmbiguousNameError, hỏi admin chọn
- Duplicate tên trong trip → DuplicateNameInTripError

Fuzzy match: exact → normalized (bỏ dấu) → Levenshtein ≤ 2.

## 7. Khi cần chi tiết

- Công thức + ví dụ số đầy đủ: `references/fund_model.md`
- Code patterns transaction: `references/transaction_patterns.md`
- Contribution kinds edge cases: `references/contribution_kinds.md`
