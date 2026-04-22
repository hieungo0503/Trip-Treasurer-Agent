---
name: zalo-agent-patterns
description: >
  Patterns cho Zalo OA webhook, intent classification, confirmation card
  format, state machine, và mock channel cho Trip Treasurer Agent.
  Đọc skill này trước khi: implement webhook handler, viết intent classifier,
  tạo node mới (parse/commit), format message gửi Zalo, implement mock channel
  để test, hoặc thêm lệnh /command mới. Bao gồm cả Zalo API quirks và
  các edge case thường gặp khi làm chatbot Zalo OA.
---

# Zalo Agent Patterns

## 1. Webhook Handler — 200 OK trong < 2s

Zalo sẽ retry nếu không nhận 200 OK trong 2s. Pattern chuẩn:

```python
@app.post("/webhook/zalo")
async def zalo_webhook(request: Request):
    # 1. Đọc body
    body = await request.body()

    # 2. Verify signature TRƯỚC (reject sớm nếu sai)
    signature = request.headers.get("X-ZEvent-Signature", "")
    if not verify_zalo_signature(body, signature, settings.zalo_app_secret):
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    payload = json.loads(body)
    event_id = payload.get("event_id") or payload.get("id", "")

    # 3. Check idempotency (Zalo retry cùng event)
    if await is_already_processed(event_id, db):
        return JSONResponse({"ok": True, "duplicate": True})

    # 4. Enqueue → return 200 NGAY, xử lý async
    await task_queue.enqueue(process_zalo_event, payload)
    return JSONResponse({"ok": True})
```

Chi tiết Zalo API quirks → `references/zalo_api.md`

## 2. Intent Classifier — Rule trước, LLM sau

80% tin nhắn phân loại được bằng regex, không cần gọi LLM.

```python
def classify_intent(text: str, state: ConversationState,
                    trip_status: TripStatus | None) -> Intent:
    text_lower = text.lower().strip()

    # --- Commands (exact match) ---
    if text_lower.startswith("/trip_new"):   return Intent.TRIP_NEW
    if text_lower in ("/trips",):            return Intent.TRIP_LIST
    if text_lower in ("/quy",):             return Intent.QUERY_FUND
    if text_lower in ("/tongket",):         return Intent.QUERY_SUMMARY
    if text_lower in ("/cuatoi",):          return Intent.QUERY_MINE
    if text_lower in ("/nap_cua_toi",):     return Intent.QUERY_TOPUP_MINE
    if text_lower in ("/chiaai",):          return Intent.QUERY_SETTLEMENT
    if text_lower in ("/help",):            return Intent.HELP_OVERVIEW
    if text_lower.startswith("/help "):     return Intent.HELP_TOPIC
    if text_lower in ("/lenh","/menu"):     return Intent.HELP_OVERVIEW
    if text_lower in ("/share",):           return Intent.HELP_SHARE
    if text_lower.startswith("/huy_auto "): return Intent.HUY_AUTO_ADVANCE
    if text_lower in ("/rebuild_sheet",):   return Intent.REBUILD_SHEET

    # --- State-dependent (AWAITING_CONFIRM) ---
    if state == ConversationState.AWAITING_CONFIRM:
        if re.match(r'^(ok|đồng ý|✅|xác nhận|khởi động)$', text_lower):
            return Intent.CONFIRM
        if text_lower.startswith("sửa "):   return Intent.AMEND
        if re.match(r'^(huỷ|huy|cancel|❌)$', text_lower):
            return Intent.CANCEL_PENDING

    # --- Initial topup (COLLECTING_TOPUP state only) ---
    if trip_status == TripStatus.COLLECTING_TOPUP:
        if re.search(r'[\wÀ-ỹ]+\s+(đã nạp|góp|nạp|đã góp)\s+\d', text_lower):
            return Intent.LOG_INITIAL_TOPUP

    # --- Advance expense ("ứng X để chi Y") ---
    if re.search(r'ứng\s+\d.*(để chi|để trả|để góp|cho|trả)', text_lower):
        return Intent.LOG_ADVANCE_EXPENSE

    # --- Topup ("nạp X" / "góp X") ---
    if re.search(r'^(nạp|góp|nap|gop)\s+\d', text_lower):
        return Intent.LOG_TOPUP

    # --- Expense ("chi X" / "trả X" / số tiền đơn giản) ---
    if re.search(r'(chi|trả|tra|thanh toán)\s+\d', text_lower):
        return Intent.LOG_EXPENSE
    if re.search(r'^\d+[ktr]', text_lower):
        return Intent.LOG_EXPENSE

    # --- Help natural language ---
    if any(kw in text_lower for kw in
           ['hướng dẫn','help','làm sao','cách dùng','không biết','hỗ trợ']):
        return Intent.HELP_OVERVIEW

    # --- Fallback: LLM classify ---
    return Intent.UNKNOWN  # orchestrator sẽ gọi LLM
```

Chi tiết patterns + edge cases → `references/intent_rules.md`

## 3. Card Templates — Format chuẩn gửi Zalo

Zalo OA text message không render markdown. Dùng text thuần + emoji + ─ để tạo visual.

**Template expense confirm (Flow B):**
```
┌──────────────────────────────────┐
│ ⚠️ Xác nhận khoản chi             │
│ ────────────────────────────────  │
│ 💰 Số tiền:   {amount}           │
│ 🍖 Nội dung:  {description}      │
│ 👤 Người chi: {payer_name}       │
│ 🕐 Thời gian: {time_vn}          │
│ 👥 Chia cho:  {split_names}      │
│ ────────────────────────────────  │
│ 💳 Quỹ hiện tại: {fund_before}   │
│ 💳 Sau khi chi:  {fund_after}    │
│ ────────────────────────────────  │
│ ✅ "ok" để ghi                    │
│ ✏️ "sửa <trường> <giá trị>"       │
│ ❌ "huỷ"                           │
└──────────────────────────────────┘
```

**Template advance confirm (Flow D):**
```
┌────────────────────────────────────────┐
│ ⚠️ Xác nhận: Ứng tiền + Chi tiêu       │
│ 💰 Số tiền:        {amount}            │
│ 🎯 Nội dung:       {description}       │
│ 👤 Người chi:      {payer} (ứng tiền túi) │
│ ────────────────────────────────────────│
│ 📋 Bot sẽ ghi 2 mục liên kết:          │
│  1. {payer} ứng: {amount}              │
│  2. Chi {description}: {amount}        │
│ ────────────────────────────────────────│
│ 💳 Quỹ KHÔNG thay đổi (vẫn {fund})     │
│ ────────────────────────────────────────│
│ ✅ "ok" / ✏️ "sửa ..." / ❌ "huỷ"       │
└────────────────────────────────────────┘
```

**Template auto-advance card (Flow C — quỹ không đủ):**
```
┌──────────────────────────────────────┐
│ ⚠️ Xác nhận khoản chi                │
│ 💰 Số tiền: {amount}                 │
│ 💳 Quỹ hiện có: {fund} — KHÔNG ĐỦ   │
│ ⚠️ Thiếu: {deficit}                  │
│ ──────────────────────────────────────│
│ 1️⃣ Bạn ứng tự động {deficit}         │
│    → Gõ "ok" (mặc định)             │
│                                      │
│ 2️⃣ Ai đó đã ứng trước rồi?           │
│    → Gõ "huỷ" → ghi ứng trước →    │
│      gõ lại khoản chi này           │
│ ──────────────────────────────────────│
│ ✅ "ok" = phương án 1               │
│ ❌ "huỷ" = phương án 2              │
└──────────────────────────────────────┘
```

Tất cả card templates → `references/card_templates.md`

## 4. State Machine — Per User

```
IDLE ──[user gửi expense/topup]──→ PARSING (< 5s)
                                       │ parse OK
                                       ▼
IDLE ←─[huỷ / timeout 30min]── AWAITING_CONFIRM
                                       │ "sửa ..."
                                       ↔ AMENDING
                                       │ "ok"
                                       ▼
                                    COMMITTED ──→ IDLE
```

State lưu trong `conversations.state`. Timeout 30 phút auto-reset về IDLE.

```python
# Kiểm tra pending timeout
if conv.pending_id:
    pending = await db.fetch_pending(conv.pending_id)
    if pending and pending.expires_at < utcnow():
        await db.soft_delete_pending(pending.id)
        conv.state = ConversationState.IDLE
        conv.pending_id = None
        await db.update_conversation(conv)
        await send_zalo(user_id, "⏰ Đã huỷ xác nhận do quá 30 phút không phản hồi.")
```

## 5. Mock Channel — Test local không cần Zalo

```python
# POST /mock/send — user gửi tin
@app.post("/mock/send")
async def mock_send(body: MockSendRequest):
    """Simulate user gửi tin nhắn qua Zalo."""
    fake_webhook = {
        "event_name": "user_send_text",
        "user_id": body.zalo_user_id,
        "event_id": f"mock-{uuid4()}",
        "timestamp": int(time.time() * 1000),
        "message": {"text": body.text},
    }
    await process_zalo_event(fake_webhook)
    # Trả về các tin bot đã gửi
    return {"bot_replies": mock_outbox.get(body.zalo_user_id, [])}

# GET /mock/inbox/{user_id} — xem tin bot đã gửi
@app.get("/mock/inbox/{user_id}")
async def mock_inbox(user_id: str):
    return {"messages": mock_outbox.get(user_id, [])}
```

## 6. Amend (sửa pending)

```python
def apply_amendment(pending: PendingExpense, amend_text: str) -> PendingExpense:
    """Parse "sửa <trường> <giá trị>" và update pending."""
    # Whitelist fields có thể sửa — KHÔNG cho sửa status, trip_id, id, ...
    ALLOWED = {
        "số": "amount_vnd",
        "nội dung": "description",
        "nguoichi": "payer_id",
        "thoigian": "occurred_at",
    }
    for key, field in ALLOWED.items():
        if amend_text.startswith(f"sửa {key} "):
            value = amend_text[len(f"sửa {key} "):].strip()
            return update_pending_field(pending, field, value)

    raise InvalidAmendError(f"Không thể sửa trường đó. Cho phép: {list(ALLOWED.keys())}")
```

## 7. Khi cần chi tiết

- Zalo API quirks + signature verify: `references/zalo_api.md`
- Intent rules đầy đủ + edge cases: `references/intent_rules.md`
- Tất cả card templates: `references/card_templates.md`
- Flow A-I chi tiết: xem `PLAN_v2.3.md` section 2.4
