---
name: reliability-security
description: >
  Retry, timeout, circuit breaker, input validation, output filter, permission
  boundaries cho Trip Treasurer Agent. PHẢI đọc skill này trước khi: viết bất
  kỳ external call nào (LLM, Google Sheets, Zalo API, Drive API), implement
  input validation hoặc output filter, thêm permission check, implement rate
  limiting, hoặc viết bất cứ thứ gì trong app/reliability/ hoặc app/security/.
  Code pattern trong references/ có thể copy-paste trực tiếp.
---

# Reliability & Security — Quick Reference

## 1. Retry Policy per Service

Dùng `tenacity`. Config đầy đủ → `references/retry_configs.py`

| Service | Max retry | Total budget | Non-retriable |
|---|---|---|---|
| LLM Viettel | 3 | 15s | 400, 401, 403, 422 |
| Google Sheets | 5 | 45s | 400, 401, 403, 404 |
| Google Drive | 5 | 45s | Same as Sheets |
| Zalo send | 4 | 10s | 400, 401, 403 |
| SQLite/Postgres | 3 | 1s | Chỉ deadlock/busy |

```python
# Import dùng liền — không cần viết lại
from app.reliability.retry import llm_retry, sheets_retry, zalo_retry

@llm_retry
async def call_llm(prompt: str) -> dict: ...

@sheets_retry
async def append_sheet_row(data: dict) -> None: ...
```

## 2. Timeout Budget per Flow

```python
# Tổng budget per flow
FLOW_BUDGETS = {
    "text_expense":  timedelta(seconds=5),   # webhook → reply
    "image_bill":    timedelta(seconds=15),  # webhook → reply (OCR)
    "query_fund":    timedelta(seconds=3),
    "trip_new":      timedelta(seconds=8),
}

# Timeout per step
STEP_TIMEOUTS = {
    "llm_parse":    15,  # seconds
    "llm_classify": 5,
    "ocr":          10,
    "sheets_write": 30,
    "zalo_send":    10,
    "db_query":     5,
}
```

Dùng `RequestContext.check_deadline(step_name)` trước mỗi step.

## 3. Circuit Breaker

4 circuit breakers đã implement trong `app/reliability/circuit_breaker.py`:

```python
from app.reliability.circuit_breaker import (
    llm_circuit,
    sheets_circuit,
    drive_circuit,
    zalo_circuit,
)

# Usage
if not llm_circuit.can_attempt():
    # Fallback: dùng rule-based parser
    return rule_parse_expense(text)

try:
    result = await call_llm(prompt)
    llm_circuit.record_success()
    return result
except RetriableError:
    llm_circuit.record_failure()
    raise
```

Code đầy đủ → `references/circuit_breaker.py`

## 4. Input Validation — 4 Tầng

```python
# Tầng 1: Length limit
def validate_length(text: str):
    if len(text) > 500:
        raise InputTooLongError(len(text))

# Tầng 2: Encoding (zero-width chars)
def validate_encoding(text: str):
    ZERO_WIDTH = ['\u200b', '\u200c', '\u200d', '\ufeff']
    if any(ch in text for ch in ZERO_WIDTH):
        raise InvalidEncodingError()

# Tầng 3: Prompt injection detect (log, không reject cứng)
INJECTION_PATTERNS = re.compile(
    r'ignore.*(previous|prior|above).*(instruction|prompt)'
    r'|you\s+are\s+now\s+'
    r'|act\s+as\s+(a\s+)?(different|admin|system)'
    r'|bỏ\s+qua.*(lệnh|chỉ dẫn)\s+trước'
    r'|đóng\s+vai.*(là\s+)?admin',
    re.IGNORECASE
)
def detect_injection(text: str) -> bool:
    return bool(INJECTION_PATTERNS.search(text))

# Tầng 4: Amend field whitelist
AMEND_WHITELIST = {"số", "nội dung", "nguoichi", "thoigian", "ghi chú"}
def validate_amend_field(field: str):
    if field.lower() not in AMEND_WHITELIST:
        raise InvalidAmendFieldError(field, AMEND_WHITELIST)
```

Code đầy đủ + patterns → `references/input_validation.py`

## 5. Output Filter (LLM response)

```python
# Validate schema trước khi dùng
def safe_parse_llm_output(raw: str, schema: type[BaseModel]) -> BaseModel:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise LLMOutputError("not JSON")
    try:
        return schema.model_validate(data)
    except ValidationError as e:
        raise LLMOutputError(f"schema invalid: {e}")

# Filter content nguy hiểm
RESPONSE_FILTER_PATTERNS = re.compile(
    r'You\s+are\s+an?\s+(AI|assistant|parser)'
    r'|system\s+prompt'
    r'|(Claude|GPT|OpenAI|Anthropic)',
    re.IGNORECASE
)
def filter_response(text: str) -> str:
    if RESPONSE_FILTER_PATTERNS.search(text):
        log.warning("output.filter.blocked")
        return "Bot không thể xử lý yêu cầu này. Thử /help để xem hướng dẫn."
    return text
```

## 6. Permission Check

```python
from app.security.permissions import require_admin, require_trip_member

# Decorator cho admin-only handler
@require_admin
async def handle_trip_new(ctx: RequestContext, text: str): ...

@require_admin
async def handle_rebuild_sheet(ctx: RequestContext, text: str): ...

# Check trip membership cho mọi action ghi data
@require_trip_member
async def handle_log_expense(ctx: RequestContext, text: str): ...

# Implementation
def require_admin(handler):
    @functools.wraps(handler)
    async def wrapper(ctx: RequestContext, *args, **kwargs):
        if ctx.member_id not in settings.admin_member_id_list:
            await reply(ctx, "⛔ Lệnh này chỉ dành cho admin.")
            return
        return await handler(ctx, *args, **kwargs)
    return wrapper
```

## 7. Sheet Security

```python
# LUÔN dùng RAW, KHÔNG dùng USER_ENTERED
# USER_ENTERED cho phép formula injection: user gõ =IMPORTXML(...)
sheets.values().append(
    spreadsheetId=sheet_id,
    range=range_,
    valueInputOption="RAW",  # ← KHÔNG BAO GIỜ đổi thành USER_ENTERED
    body={"values": [row_data]},
).execute()
```

## 8. Kill Switch

```python
# Admin gõ /pause_bot
@require_admin
async def handle_pause_bot(ctx):
    await db.set_setting("bot_enabled", "false")
    await reply(ctx, "🔴 Bot đã pause. Gõ /resume_bot để bật lại.")

# Middleware check ở webhook handler
async def zalo_webhook(request: Request):
    if not await db.get_setting("bot_enabled", default="true") == "true":
        return JSONResponse({"ok": True, "paused": True})
    # ... normal processing
```

## 9. Pre-deploy Checklist (tóm tắt)

- [ ] `.env` trong `.gitignore`, pre-commit `detect-secrets` cài
- [ ] Zalo signature verify mọi webhook
- [ ] Whitelist `oa_id` và `zalo_user_id` từ `members.active`
- [ ] Admin decorator trên mọi admin handler
- [ ] Google service account quyền Editor (không Owner)
- [ ] Sheet ghi `valueInputOption=RAW`
- [ ] SQL prepared statement tất cả query
- [ ] Rate limit per user active
- [ ] Circuit breaker 4 services active
- [ ] Invariant assert sau mọi DB commit
- [ ] Trip isolation: mọi query có `WHERE trip_id=?`

Checklist đầy đủ 50 items → `RELIABILITY_SECURITY.md` section E.1

## 10. Khi cần chi tiết

- Retry code có thể copy-paste: `references/retry_configs.py`
- Circuit breaker đầy đủ: `references/circuit_breaker.py`
- Input validation patterns: `references/input_validation.py`
