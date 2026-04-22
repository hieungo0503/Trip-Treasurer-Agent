# Fund Model — Ví dụ số đầy đủ

## Kịch bản 1: Bình thường (chi từ quỹ)

4 người nạp đầu 1tr/người → quỹ = 4tr.

```
Contributions:
  C1: Đức nạp 1tr (initial_topup)  → quỹ = 1tr
  C2: Hà  nạp 1tr (initial_topup)  → quỹ = 2tr
  C3: Long nạp 1tr (initial_topup) → quỹ = 3tr
  C4: Minh nạp 1tr (initial_topup) → quỹ = 4tr

Expenses (chi từ quỹ, không linked):
  E1: Đức chi 500k đồ nướng → quỹ = 3.5tr
  E2: Hà  chi 800k ăn tối   → quỹ = 2.7tr
  E3: Long chi 700k taxi     → quỹ = 2.0tr

fund_balance = 4tr - (500k + 800k + 700k) = 2.0tr ✅

fair_share = (500k + 800k + 700k) / 4 = 500k/người

Balances:
  Đức:  contrib=1tr, fair=500k, net=+500k
  Hà:   contrib=1tr, fair=500k, net=+500k
  Long: contrib=1tr, fair=500k, net=+500k
  Minh: contrib=1tr, fair=500k, net=+500k

Σ net = 2tr = fund_balance ✅  (mọi người đóng đều, chi đều → net đều)
```

## Kịch bản 2: Advance (ứng tiền, quỹ không đổi)

Tiếp kịch bản 1. Quỹ còn 2tr. Đức muốn chi thêm 1.5tr thuê thuyền.
Đức gõ: "ứng 1.5tr để chi thuê thuyền".

```
Ghi 2 record liên kết:
  C5: Đức ứng 1.5tr (advance, linked_expense_id=E4) → quỹ KHÔNG ĐỔI
  E4: chi thuê thuyền 1.5tr (linked) → quỹ KHÔNG ĐỔI

fund_balance sau = 4tr (topup) - [500k+800k+700k] (unlinked) = 2tr ✅
(E4 là linked → không trừ quỹ thực)

Balances mới:
  Đức:  contrib = 1tr + 1.5tr(advance) = 2.5tr
        fair    = (2tr + 1.5tr) / 4 = 875k
        net     = 2.5tr - 875k = +1.625tr ← được hoàn nhiều nhất
  Hà:   contrib=1tr, fair=875k, net=+125k
  Long: contrib=1tr, fair=875k, net=+125k
  Minh: contrib=1tr, fair=875k, net=+125k

Σ net = 1.625tr + 125k + 125k + 125k = 2tr = fund_balance ✅
```

## Kịch bản 3: Auto-advance (quỹ không đủ, bot tự xử lý)

Tiếp kịch bản 2. Quỹ còn 2tr. Chi 2.5tr tiền khách sạn.

```
Bot phát hiện: quỹ 2tr < 2.5tr → thiếu 500k
Bot đề xuất card 2 phương án → Đức chọn "ok" (auto-advance)

Ghi:
  C6: Đức ứng tự động 500k (auto_advance, linked_expense_id=E5)
  E5: chi khách sạn 2.5tr (linked)

fund_balance = 4tr - [500k+800k+700k] (unlinked) = 2tr ✅
(E5 linked → không trừ quỹ; C6 auto_advance → không tăng quỹ)

Assertion sau commit:
  assert fund_balance >= 0 ✅
```

## Kịch bản 4: Quỹ âm BUG — không bao giờ được xảy ra

```python
# Nếu xảy ra thì đây là bug trong code:
fund_balance = compute_fund_balance(contribs, expenses)
assert fund_balance >= 0, f"BUG: fund_balance={fund_balance}"
```

Nguyên nhân thường gặp:
1. Expense linked nhưng contribution bị soft-delete → linked_expense_id không còn valid
2. Query thiếu `WHERE status='active'` → tính cả cancelled records
3. advance không được link với expense → tính sai unlinked_expense_total

## Cách debug khi fund_balance sai

```python
# Step 1: Lấy tất cả contributions và expenses của trip
contribs = await db.fetch_all(
    "SELECT * FROM contributions WHERE trip_id=? ORDER BY created_at",
    (trip_id,)
)
expenses = await db.fetch_all(
    "SELECT * FROM expenses WHERE trip_id=? ORDER BY created_at",
    (trip_id,)
)

# Step 2: Tính manual
topup_total = sum(c.amount_vnd for c in contribs
                  if c.status=='active'
                  and c.kind in ('initial_topup', 'extra_topup'))

linked_ids = {c.linked_expense_id for c in contribs
              if c.status=='active' and c.linked_expense_id}

unlinked_total = sum(e.amount_vnd for e in expenses
                     if e.status=='active' and e.id not in linked_ids)

print(f"topup={topup_total}, unlinked_expense={unlinked_total}")
print(f"fund_balance={topup_total - unlinked_total}")

# Step 3: Chạy verify_fund_invariants để thấy vi phạm cụ thể
violations = verify_fund_invariants(members, contribs, expenses)
for v in violations:
    print(f"VIOLATION: {v.name} — {v.detail}")
```
