# Plan xây dựng AI Agent quản lý chi tiêu du lịch nhóm qua Zalo

**Phiên bản:** 2.3
**Ngày cập nhật:** 19/04/2026

**Thay đổi lớn so với v2.2:**
1. **Multi-trip lifecycle là first-class feature** — member tái sử dụng giữa các chuyến, trip là đơn vị isolation.
2. **1 Google Sheet riêng cho mỗi trip** (auto-provisioned từ template).
3. **Thêm nguyên tắc thiết kế #8**: Trip isolation, Member reuse.
4. **Thêm Flow H, I**: tạo trip với member cũ, xem lại chuyến cũ.
5. **Lệnh mới**: `/trips`, `/trip_view`, `/trip_switch`, `/trip_archive`, `/trip_export`, `/trip_purge`.
6. **Backup strategy 3-tier**, data retention policy rõ ràng.
7. **Tách phụ lục** `RELIABILITY_SECURITY.md` — toàn bộ production-grade checklist (retry, timeout, circuit breaker, input/output validation, permissions, tracing, eval pipeline, metrics, incident response).
8. Schema DB mở rộng: `trips.sheet_id/sheet_url`, `conversations.active_trip_id`, `audit_log.trip_id`, `sheet_outbox.trip_id`.

**File đi kèm:**
- [HELP_CONTENT.md](./HELP_CONTENT.md) — nội dung đầy đủ 9 file help markdown
- [RELIABILITY_SECURITY.md](./RELIABILITY_SECURITY.md) — production-grade spec, checklist, code pattern

**Trạng thái:** Phase 2 — hoàn thành (kể cả Telegram channel). Phase 1: 370 tests (87%). Phase 2: +58 tests (test_zalo_channel, test_sheets, test_telegram_channel). E2E integration test full flow passed.

---

## 🟢 TIẾN ĐỘ THỰC TẾ (cập nhật 23/04/2026 — session 5)

### Đã xong ✅

**Domain layer** (`app/domain/`)
- [x] `fund.py` — `compute_fund_balance`, `check_expense_against_fund`, `verify_fund_invariants`
- [x] `settlement.py` — greedy minimum-transaction algorithm
- [x] `fuzzy_match.py` — exact → normalized → Levenshtein ≤ 2
- [x] `member_resolver.py` — resolve/reuse/placeholder member logic
- [x] `models.py` — tất cả Pydantic models

**Utils** (`app/utils/`)
- [x] `money.py` — `parse_money`, `format_money`
- [x] `vn_time.py` — múi giờ VN

**Storage** (`app/storage/`)
- [x] `db.py` — SQLite async + schema init
- [x] `repositories/trip_repo.py` — thêm `get_trips_by_status()` **[session 5]**
- [x] `repositories/member_repo.py`, `expense_repo.py`, `conversation_repo.py`
- [x] `repositories/__init__.py` — export `AuditLogRepository`, `ContributionRepository`, `PendingRepository`, `SheetOutboxRepository`, ...

**Reliability + Security + Observability**
- [x] `reliability/circuit_breaker.py` — self-implemented circuit breaker (`llm_circuit`, `sheets_circuit`, `drive_circuit`, `zalo_circuit`)
- [x] `reliability/retry.py` — tenacity retry configs
- [x] `security/input_validation.py` — Pydantic + length + encoding + prompt injection regex
- [x] `security/permissions.py` — `@require_admin` decorator, permission checks
- [x] `observability/logging.py` — structlog JSON setup; remove `add_logger_name` (incompatible với PrintLoggerFactory) **[session 5]**
- [x] `observability/metrics.py` — Prometheus counters/gauges; thêm zalo/sheets/drive metrics **[session 4]**
- [x] `observability/tracing.py` — OpenTelemetry setup

**Tools**
- [x] `tools/llm.py` — LLM client + retry + circuit breaker + rule-based fallback; parser cho: `expense`, `topup`, `advance_expense`, `trip_new`, `initial_topup`, `classify_unknown_intent`
- [x] `tools/ocr.py` — stub Phase 1 (confidence=0.0)
- [x] `tools/sheets.py` — **Phase 2**: Google Sheets API thật — append_expense_row, append_contribution_row, rebuild_sheet_from_db, update_summary_tab, ensure_headers; circuit breaker + retry + RAW write
- [x] `tools/sheet_provisioner.py` — **Phase 2**: Drive API copy template → sheet per trip, share_sheet_with_user; graceful fallback (None, None) khi fail
- [x] `tools/sheet_projector.py` — **Phase 2**: dispatch thật theo op (expense_row, contribution_row, rebuild_sheet, update_summary, provision_sheet retry)

**Channel**
- [x] `channels/mock.py` — `POST /mock/send` endpoint test local
- [x] `channels/zalo.py` — **Phase 2**: HMAC-SHA256 signature verify, parse webhook (text/image/follow), send reply via Zalo OA API v3, token refresh helper; retry + circuit breaker
- [x] `channels/telegram.py` — **Phase 2 (session 4)**: X-Telegram-Bot-Api-Secret-Token verify, parse update (text/photo/document/caption/edited_message), send reply, `/webhook/telegram/register_webhook` endpoint, `/webhook/telegram/webhook_info` debug endpoint

**Help content**
- [x] `help/overview.md`, `chi.md`, `nap.md`, `ung.md`, `anh.md`, `admin.md`, `chiatien.md`, `share.md`, `welcome.md`

**Entrypoint**
- [x] `main.py` — **Phase 2**: include zalo_router + telegram_router; `/health` thêm drive circuit + config flags (`zalo_configured`, `telegram_configured`, `google_configured`); version 0.3.0

**Config**
- [x] `config.py` — thêm `telegram_bot_token`, `telegram_webhook_url`, `telegram_webhook_secret` **[session 4]**
- [x] `.env` — điền thật: `TELEGRAM_BOT_TOKEN`, `LLM_API_KEY`, `DATABASE_URL`, `MOCK_CHANNEL_ENABLED=true` **[session 4]**

**Tests** (370 + 58 = 428 passed)
- [x] `test_fund.py`, `test_settlement.py`, `test_fuzzy_match.py`, `test_member_resolver.py`
- [x] `test_money.py`, `test_utils.py`, `test_intents.py`
- [x] `test_circuit_breaker.py`, `test_input_validation.py`
- [x] `test_storage.py`
- [x] `test_trip_resolver.py` — 12 unit tests cho trip_resolver
- [x] `test_permissions.py` — 14 unit tests: `@require_admin`, `@require_trip_member`, `_reply` helper (coverage 100%)
- [x] `test_observability.py` — 16 unit tests: logging, tracing, metrics
- [x] `test_e2e_mock.py` — 65 E2E scenarios qua mock channel
- [x] `test_zalo_channel.py` — **Phase 2**: 17 tests: signature verify (5), parse event (7), send message (4), webhook endpoint (4)
- [x] `test_sheets.py` — **Phase 2**: 16 tests: append (4), rebuild (2), summary (1), provisioner (4), share (2)
- [x] `test_telegram_channel.py` — **Phase 2 (session 4)**: 25 tests: verify secret (3), parse update (10), send message (6), webhook endpoints (6)

**Git**
- [x] Repo init, remote `https://github.com/hieungo0503/Trip-Treasurer-Agent.git`
- [x] Stop hook auto-commit + push sau mỗi Claude Code session
- [x] `.gitignore` đầy đủ (secrets, .venv, __pycache__, .db, ...)
- [x] 4 commits local trên main (chưa push — cần PAT/SSH key)

---

**Bugs đã phát hiện & fix trong session 2:**
- [x] `orchestrator.py`: `CONFIRM`/`CANCEL_PENDING` sai nằm trong `_needs_trip` → trip_new confirm bị block
- [x] `commit_expense.py`, `commit_advance_expense.py`: `confirmed_by=ctx.zalo_user_id` → FOREIGN KEY fail (phải dùng `member_id`)
- [x] `orchestrator.py`: import `utc_to_vn` từ `vn_time` nhưng function không tồn tại → gỡ import thừa

**Coverage improvements trong session 3 (+62 tests, coverage 79.6% → 87%):**
- [x] `security/permissions.py`: 0% → 100%
- [x] `observability/logging.py`: 53% → 100%
- [x] `observability/tracing.py`: 38% → 96%
- [x] `agent/orchestrator.py`: 67% → 84% (+30 E2E scenarios)
- [x] Stop hook auto-commit message: đổi format sang `feat+test(N files): name1,name2,name3`

**Bugs đã phát hiện & fix trong session 5 (commit b3100f1):**
- [x] `intents.py`: `AWAITING_CONFIRM` check nằm SAU `is_new_user → WELCOME` → user mới gửi "ok" bị classify là WELCOME thay vì CONFIRM. **Fix**: chuyển AWAITING_CONFIRM check lên TRƯỚC is_new_user block.
- [x] `orchestrator.py`: `CONFIRM`/`CANCEL_PENDING` không có trong `_no_member_ok` → user mới (chưa có member_id) bị block khi confirm initial_topup. **Fix**: thêm CONFIRM + CANCEL_PENDING vào `_no_member_ok`.
- [x] `orchestrator.py`: user mới (`is_new_user=True`) không được resolve `trip_status` → intent classifier không biết trip đang COLLECTING_TOPUP. **Fix**: thêm `elif is_new_user: collecting_trips = get_trips_by_status("collecting_topup")`.
- [x] `commit_initial_topup.py`: không link `zalo_user_id` → placeholder member sau khi confirm → user mới vẫn là "new user" cho các request sau. **Fix**: gọi `member_repo.link_zalo(member_id, zalo_user_id)` khi xác nhận.
- [x] `domain/fund.py`: `sum_nets_not_equal_fund` false positive do tolerance cứng 1đ — với 3 người chia đều 200k, integer floor division để lại 2đ gap. **Fix**: tolerance = `Σ (expense.amount_vnd % len(split_member_ids))` tính theo từng expense.
- [x] `observability/logging.py`: `structlog.stdlib.add_logger_name` không tương thích với `PrintLoggerFactory` → AttributeError khi khởi động. **Fix**: gỡ processor này.
- [x] `trip_repo.py`: thiếu method `get_trips_by_status(status)` cần cho orchestrator. **Fix**: thêm method.

**Integration test thực tế passed (session 5):**
- [x] Hà (new user) gửi "Hà đã nạp 500k" → confirmation card ✅
- [x] Hà gửi "ok" → "✅ 500.000đ — Hà", zalo_user_id linked ✅
- [x] Long tương tự → trip auto-ACTIVE (3/3) ✅
- [x] Đức "chi 200k tiền ăn sáng" → confirm → committed ✅
- [x] `/quy` → 1.300.000đ còn lại ✅
- [x] `/tongket` → per-member net balances (+433.334đ mỗi người) ✅

### Còn lại 🔲

**Phase 1 — chưa làm (không blocking):**
- [ ] `security/output_filter.py`, `security/prompt_injection.py` — stub trong input_validation
- [ ] `reliability/timeouts.py` — timeout per-operation config
- [ ] `utils/idempotency.py` — helper idempotency check
- [ ] `evals/golden_dataset.json` + `evals/run_eval.py` — parser eval pipeline
- [ ] `scripts/backup_db.sh`, `scripts/backup_offsite.sh`, `scripts/cleanup.py` — backup/maintenance
- [ ] `docs/runbook.md`, `docs/incident_response.md`

**Phase 2 — ✅ HOÀN THÀNH (session 4-5, 23/04/2026):**
- [x] `channels/zalo.py` — HMAC-SHA256 verify + parse + send reply
- [x] `channels/telegram.py` — Bot API verify + parse + send + register webhook
- [x] `tools/sheets.py` — Google Sheets API thật (append, rebuild, summary)
- [x] `tools/sheet_provisioner.py` — Drive API copy template thật + share
- [x] `tools/sheet_projector.py` — dispatch thật theo op
- [x] `main.py` — wire /webhook/zalo + /webhook/telegram
- [ ] **Còn lại để deploy thật**: Zalo OA credentials + webhook URL public (HTTPS server hoặc ngrok)
- [ ] **Còn lại để deploy thật**: Sheet template setup + `GOOGLE_SHEET_TEMPLATE_ID`, `GOOGLE_SHEET_PARENT_FOLDER_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON`
- [ ] **Còn lại để deploy thật**: Telegram webhook register (`POST /webhook/telegram/register_webhook`) với public HTTPS URL
- [ ] **Còn lại**: Push code lên GitHub (cần setup PAT hoặc SSH key: `gh auth login`)

**Phase 3 — chưa bắt đầu:**
- [ ] Hardening: rate limit, chaos test, load test
- [ ] Backup cron setup
- [ ] Alert rules Prometheus/Grafana
- [ ] `/trip_export` CSV implementation

---

---

## 1. Tổng quan & nguyên tắc thiết kế

### 1.1. Mục tiêu nghiệp vụ

Xây dựng AI Agent hoạt động như "thủ quỹ số" cho nhóm bạn đi du lịch chung, với đặc thù:

- Cả nhóm có **một quỹ chung** do mọi người nạp vào từ đầu (ví dụ 1tr/người).
- Mọi khoản chi trừ vào quỹ, không phân biệt ai rút ví trả.
- Khi quỹ không đủ, **phải có người ứng tiền túi** — bot ghi nhận minh bạch.
- Cuối chuyến, bot tự tính ai được hoàn, ai phải trả thêm, với số giao dịch tối thiểu.
- **Tái sử dụng giữa nhiều chuyến** — member đã dùng bot một lần thì dùng lại cho chuyến sau, không phải re-register. Data chuyến cũ không mất.
- **User-friendly cho cả nhóm** — hệ thống help đầy đủ, tin mẫu copy-paste cho admin giới thiệu bot.

### 1.2. Nguyên tắc thiết kế cốt lõi (8 nguyên tắc)

1. **Human-in-the-loop tuyệt đối** — không bao giờ tự ghi mà không có xác nhận rõ ràng.
2. **Reliable by design** — retry + idempotency + circuit breaker + fallback strategy cho mọi external call.
3. **Secure by default** — input validation layers, output filter, permission boundaries, rate limit.
4. **Observable from day 1** — structured JSON logging + OpenTelemetry tracing + Prometheus metrics + eval pipeline.
5. **Modular & composable** — 4 layer rạch ròi, dễ swap/mở rộng.
6. **DB is source of truth, Sheet is view** — logic dựa trên DB, Sheet chỉ để hiển thị, rebuild-able.
7. **Fund balance ≥ 0 luôn, tính theo input order** — quỹ không âm, thứ tự ghi DB quyết định.
8. **Trip isolation, Member reuse** — mỗi trip là container độc lập về data (expenses, contributions, sheet). Member là global, tái dùng qua nhiều trip.

### 1.3. Scope MVP (multi-trip first-class)

| Có trong MVP | Không có trong MVP |
|---|---|
| Tạo nhiều trip, mỗi trip isolation | >1 trip ACTIVE mỗi user cùng lúc (Phase 4) |
| Member reuse giữa trip | |
| Nhập chi tiêu tiếng Việt (chi/trả) | Voice message |
| Nhận diện bill qua ảnh (OCR + LLM) | Nhiều bill 1 ảnh |
| Xác nhận 2 chiều | Sửa chi tiêu > 24h |
| Quỹ chung, nạp đầu, auto-trừ | Nạp không đều |
| Auto-advance quỹ không đủ | |
| Intent "ứng X để chi Y" | Chia theo tỷ lệ / loại trừ |
| Chia đều cả nhóm mặc định | |
| Tạo trip 3 biến thể cú pháp | |
| Help system + welcome | |
| 1 Google Sheet per trip (auto-provision) | |
| Xem lại trip cũ, archive, export | |
| Thuật toán settlement tối thiểu giao dịch | Tích hợp VietQR |
| Múi giờ VN cố định | Multi-currency |
| Admin có lệnh đặc biệt | |
| Backup 3-tier (local + Drive) | |
| Tracing + eval pipeline (cho parser) | |

---

## 2. Kiến trúc hệ thống

### 2.1. Sơ đồ 4 layer

```
┌────────────────────────────────────────────────────────────────┐
│  LAYER 1: CHANNEL (Zalo OA)                                    │
└───────────────────────────┬────────────────────────────────────┘
                            │ HTTPS webhook (verify signature)
                            ▼
┌────────────────────────────────────────────────────────────────┐
│  LAYER 2: API GATEWAY (FastAPI)                                │
│  - /webhook/zalo  → verify → queue → 200 OK < 2s               │
│  - /api/v1/*      → REST cho agent khác                        │
│  - /health, /metrics                                           │
│  - Middleware: rate-limit, tracing, metrics                    │
└───────────────────────────┬────────────────────────────────────┘
                            │ async task
                            ▼
┌────────────────────────────────────────────────────────────────┐
│  LAYER 3: AGENT CORE                                           │
│                                                                │
│  Per-user: IDLE → PARSING → AWAITING_CONFIRM → COMMITTED       │
│  Per-trip: DRAFT → COLLECTING_TOPUP → ACTIVE → SETTLED → ARCH  │
│                                                                │
│  Pipeline per request:                                         │
│   input_validation → intent_classify → resolve_trip_context →  │
│   parse_node → render_confirmation → commit_node → project     │
│                                                                │
│  Mỗi step có: retry policy, timeout, fallback, trace span      │
└─────┬──────────────────┬──────────────────┬───────────────────┘
      │                  │                  │
      ▼                  ▼                  ▼
┌──────────┐      ┌─────────────────┐   ┌─────────────────┐
│ LLM Tool │      │ Storage (DB)    │   │ Sheet Projector │
│ gpt-oss  │      │ SOURCE OF TRUTH │   │ (per-trip sheet,│
│ 120b     │      │ + Member global │   │  from template) │
│ Viettel  │      │ + Trip scoped   │   │                 │
│          │      │                 │   │                 │
│ + OCR    │      │ + Backup 3-tier │   │                 │
│ Paddle   │      │ + Audit log     │   │                 │
└──────────┘      └─────────────────┘   └─────────────────┘
  LAYER 4: TOOLS & STORAGE
```

### 2.2. DB vs Sheet — triết lý

**DB là source of truth** (transaction atomicity, FK, unique index, backup).

**Sheet là view user-friendly** (dễ share, dễ nhìn, rebuild-able).

**1 sheet per trip** (auto-provisioned từ template khi tạo trip):
- Không mất data chuyến cũ khi tạo chuyến mới
- User share link sheet riêng cho từng nhóm
- Sheet trở nên quá dài không còn là vấn đề
- Rebuild từ DB dễ hơn (mỗi trip độc lập)

### 2.3. Stack kỹ thuật

| Thành phần | Lựa chọn |
|---|---|
| Ngôn ngữ | Python 3.11+ |
| Web framework | FastAPI |
| Agent orchestration | State machine tự viết |
| LLM | `openai/gpt-oss-120b` via Viettel Netmind |
| OCR | PaddleOCR + LLM vision fallback |
| DB | SQLite (MVP) → PostgreSQL (scale) |
| DB migration | Alembic |
| View layer | Google Sheets API v4 + Drive API (copy template) |
| Retry | `tenacity` |
| Circuit breaker | `pybreaker` hoặc self-implemented |
| Rate limit | `slowapi` |
| Tracing | OpenTelemetry + console/Jaeger exporter |
| Metrics | `prometheus-client` + Grafana |
| Secret | .env + docker secrets |
| Queue | asyncio + DB outbox |
| Deploy | Docker Compose trên server Đức |
| Backup | SQLite dump + Google Drive upload (encrypted) |

### 2.4. Các flow nghiệp vụ chính (9 flow)

- **Flow A** — Tạo chuyến & nạp quỹ đầu (3 biến thể cú pháp)
- **Flow B** — Chi tiêu bình thường khi quỹ đủ
- **Flow C** — Chi khi quỹ không đủ → auto-advance
- **Flow D** — User chủ động "ứng X để chi Y"
- **Flow E** — Nạp thêm vào quỹ
- **Flow F** — User mới nhắn bot lần đầu (welcome)
- **Flow G** — User hỏi help / gõ sai
- **Flow H** — Tạo trip mới với member cũ (NEW v2.3)
- **Flow I** — Xem lại chuyến cũ (NEW v2.3)

(Chi tiết Flow A-G xem v2.2 section 2.4; v2.3 chỉ cập nhật Flow A và thêm Flow H, I — xem section 2.4.1, 2.4.8, 2.4.9 dưới đây.)

#### 2.4.1. Flow A — Tạo chuyến & nạp quỹ đầu (update v2.3)

3 biến thể như v2.2, nhưng có thêm logic **member reuse**:

**Khi admin khai tên trong trip mới:**

```python
for name in admin_supplied_names:
    matches = search_members_by_display_name(name, active=True)
    
    if len(matches) == 0:
        # Member mới hoàn toàn → tạo placeholder (zalo_user_id=NULL)
        create_placeholder_member(display_name=name)
        # User này sẽ phải nhắn bot lần đầu để link
        
    elif len(matches) == 1:
        # Match 1 → reuse member cũ
        reuse_existing_member(matches[0])
        # Nếu member đã có zalo_user_id → bot ping trực tiếp
        if matches[0].zalo_user_id:
            notify_existing_member_invited_to_new_trip(matches[0])
        
    else:
        # 2+ match → ambiguous, hỏi admin
        raise AmbiguousNameError(name, matches)
```

**Card khi ambiguous name:**

```
⚠️ Có 2 người tên "Hà" trong hệ thống:

   1. Hà (ID M042)
      - Đã tham gia: Hạ Long 04/2026, Phú Quốc 08/2025
      - Zalo: đã link

   2. Hà (ID M087)
      - Đã tham gia: Công ty offsite 03/2026
      - Zalo: đã link

Bạn chọn ai?
   "1" - Hà ở danh sách 1
   "2" - Hà ở danh sách 2
   "mới" - Tạo người mới (khác với 2 Hà cũ)
           → Admin sẽ cần đặt tên phân biệt
             (VD: "Hà béo", "Hà gầy") khi tạo lại
```

**Card thông báo member cũ được thêm vào trip mới:**

```
Bot → Hà (nhắn riêng):

👋 Chào Hà!
Đức vừa tạo chuyến mới và thêm bạn vào:
📍 Đà Lạt (10-12/05)
👥 Cùng: Đức, Long, Minh, An
💰 Cần nạp: 800.000đ

Xác nhận đã nạp? Gõ "ok đã nạp 800k"
```

**Với member mới (chưa có trong DB):**

Giống v2.2 — admin gửi tin mẫu vào group chat, member nhắn bot lần đầu với cú pháp `<tên> đã nạp X`.

#### 2.4.8. Flow H — Tạo trip mới với member cũ (NEW v2.3)

Tình huống: Đức đã tổ chức chuyến Hạ Long 3 tháng trước với Hà, Long, Minh. Giờ tạo chuyến Đà Lạt cùng nhóm + thêm An.

```
Đức: /trip_new Đà Lạt, 10-12/05, 5 người gồm đức hà long minh an, 800k/người

Bot parse → resolve member:
   • Đức → member M001 (bạn, admin) ✅ có sẵn
   • Hà  → member M042 ✅ có sẵn, đã link zalo
   • Long → member M043 ✅ có sẵn
   • Minh → member M044 ✅ có sẵn
   • An → KHÔNG tìm thấy → tạo placeholder M099

Bot:
┌──────────────────────────────────────┐
│ 🧳 XÁC NHẬN TẠO CHUYẾN               │
│ ────────────────────────────────────  │
│ 📍 Tên:        Đà Lạt                │
│ 📅 Thời gian:  10/05 → 12/05         │
│ 👥 5 thành viên:                     │
│    1. Đức  (bạn, admin) ♻️ đã có      │
│    2. Hà                ♻️ đã có      │
│    3. Long              ♻️ đã có      │
│    4. Minh              ♻️ đã có      │
│    5. An                ✨ mới        │
│ 💰 Nạp đầu:    800.000đ/người        │
│ 💳 Quỹ dự kiến:4.000.000đ            │
│ ────────────────────────────────────  │
│ ℹ️ Member "cũ" đã có trong hệ thống  │
│   sẽ được bot ping trực tiếp.        │
│   An (mới) cần nhắn bot với cú pháp: │
│   "An đã nạp 800k"                   │
│ ────────────────────────────────────  │
│ ✅ "ok" / ✏️ "sửa ..." / ❌ "huỷ"     │
└──────────────────────────────────────┘

Đức: ok

Bot: 
  • Tạo trip TRIP-20260510 (status=collecting_topup)
  • Copy Google Sheet template → tạo sheet mới "Đà Lạt 10-12/05"
  • Share Sheet cho service account
  • Lưu trips.sheet_id, trips.sheet_url
  • Với Đức, Hà, Long, Minh: nhắn trực tiếp "đã được thêm, xác nhận nạp"
  • Với An: không nhắn được vì chưa follow OA; bot gửi admin tin mẫu share cho group
  • Reply admin:
    "✅ Đã tạo chuyến Đà Lạt.
     📊 Đã ping 4/5 member cũ.
     📨 An (mới) chưa có trong hệ thống.
     Gõ /share để lấy tin mẫu cho nhóm.
     📎 Sheet: https://docs.google.com/..."
```

#### 2.4.9. Flow I — Xem lại chuyến cũ (NEW v2.3)

```
Đức: /trips

Bot:
┌──────────────────────────────────────┐
│ 📚 CÁC CHUYẾN CỦA BẠN                │
│ ────────────────────────────────────  │
│ 🟢 ĐANG HOẠT ĐỘNG:                    │
│   1. [TRIP-20260510] Đà Lạt          │
│      10-12/05/2026                   │
│      Quỹ: 3.2M/4M, đã chi 800k       │
│      📎 https://docs.google.com/...   │
│                                      │
│ 🔵 ĐÃ KẾT THÚC:                       │
│   2. [TRIP-20260415] Hạ Long         │
│      15-18/04/2026                   │
│      Tổng: 4M, đã quyết toán         │
│      📎 https://docs.google.com/...   │
│                                      │
│ 📜 LƯU TRỮ (> 30 ngày):               │
│   3. [TRIP-20251201] Phú Quốc        │
│      01-05/12/2025                   │
│      Tổng: 12M                       │
│      📎 https://docs.google.com/...   │
│                                      │
│ 💡 LỆNH:                              │
│   /trip_view <id>    xem chi tiết    │
│   /trip_switch <id>  đổi chuyến làm  │
│                      việc (nếu 2+)   │
│   /trip_export <id>  export CSV      │
│                      (admin only)    │
└──────────────────────────────────────┘
```

**`/trip_view TRIP-20260415`** — show chi tiết trip cũ (read-only): thành viên, tổng chi, settlement, link sheet.

**`/trip_export TRIP-20260415`** — admin export toàn bộ data trip thành CSV/JSON, tải về.

---

## 3. Mô hình domain — quỹ chung

(Không đổi so với v2.2. Xem v2.2 section 3 đầy đủ.)

**Tóm tắt:**
- 4 loại contribution: `initial_topup`, `extra_topup`, `advance`, `auto_advance`
- `fund_balance = Σ contrib(topup) − Σ expense_không_linked`
- `net_i = contribution_i − fair_share_i`
- Σ net = fund_balance (invariant)

---

## 4. Cấu trúc dữ liệu (update v2.3)

### 4.1. Database schema

```sql
-- === MEMBERS (global, cross-trip) ===
CREATE TABLE members (
  id            TEXT PRIMARY KEY,
  zalo_user_id  TEXT UNIQUE,          -- NULL được: placeholder
  display_name  TEXT NOT NULL,         -- không UNIQUE (cho phép 2 "Hà")
  full_name     TEXT,
  is_admin      BOOLEAN NOT NULL DEFAULT FALSE,
  active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_members_name_active ON members(display_name, active);

-- === TRIPS (isolation unit) ===
CREATE TABLE trips (
  id                         TEXT PRIMARY KEY,  -- 'TRIP-20260510'
  name                       TEXT NOT NULL,
  start_date                 DATE NOT NULL,
  end_date                   DATE,
  status                     TEXT NOT NULL,  -- draft|collecting_topup|active|settled|archived|cancelled
  expected_member_count      INTEGER NOT NULL,
  initial_topup_per_member   BIGINT,
  sheet_id                   TEXT,           -- Google Sheet ID
  sheet_url                  TEXT,           -- URL đầy đủ
  created_by                 TEXT NOT NULL REFERENCES members(id),
  created_at                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  settled_at                 TIMESTAMP,      -- để auto-archive sau 30 ngày
  archived_at                TIMESTAMP
);

CREATE INDEX idx_trips_status ON trips(status);
CREATE INDEX idx_trips_settled_at ON trips(settled_at) WHERE status = 'settled';

CREATE TABLE trip_members (
  trip_id    TEXT NOT NULL REFERENCES trips(id),
  member_id  TEXT NOT NULL REFERENCES members(id),
  joined_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  left_at    TIMESTAMP,                    -- soft remove qua /trip_removemember
  PRIMARY KEY (trip_id, member_id)
);

-- Constraint: display_name UNIQUE per trip (enforce ở application layer)
-- Khi admin khai 2 "Hà" trong 1 trip → reject

-- === CONTRIBUTIONS ===
CREATE TABLE contributions (
  id                 TEXT PRIMARY KEY,
  trip_id            TEXT NOT NULL REFERENCES trips(id),
  member_id          TEXT NOT NULL REFERENCES members(id),
  amount_vnd         BIGINT NOT NULL CHECK (amount_vnd > 0),
  kind               TEXT NOT NULL,  -- initial_topup|extra_topup|advance|auto_advance
  linked_expense_id  TEXT REFERENCES expenses(id),
  note               TEXT,
  occurred_at        TIMESTAMP NOT NULL,
  created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- input order
  confirmed_at       TIMESTAMP NOT NULL,
  source_event_id    TEXT UNIQUE,
  trace_id           TEXT,
  status             TEXT NOT NULL DEFAULT 'active'
);

-- === EXPENSES ===
CREATE TABLE expenses (
  id                TEXT PRIMARY KEY,
  trip_id           TEXT NOT NULL REFERENCES trips(id),
  payer_id          TEXT NOT NULL REFERENCES members(id),
  amount_vnd        BIGINT NOT NULL CHECK (amount_vnd > 0),
  category          TEXT NOT NULL,
  description       TEXT NOT NULL,
  split_method      TEXT NOT NULL DEFAULT 'equal',
  split_member_ids  TEXT NOT NULL,
  source            TEXT NOT NULL,
  source_raw        TEXT,
  ocr_confidence    REAL,
  occurred_at       TIMESTAMP NOT NULL,
  created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  confirmed_at      TIMESTAMP NOT NULL,
  confirmed_by      TEXT NOT NULL REFERENCES members(id),
  source_event_id   TEXT UNIQUE,
  trace_id          TEXT,
  status            TEXT NOT NULL DEFAULT 'active'
);

-- === PENDING CONFIRMATIONS ===
CREATE TABLE pending_confirmations (
  id             TEXT PRIMARY KEY,
  zalo_user_id   TEXT NOT NULL,
  trip_id        TEXT REFERENCES trips(id),  -- NULL nếu là pending /trip_new
  kind           TEXT NOT NULL,
  payload_json   TEXT NOT NULL,
  state          TEXT NOT NULL DEFAULT 'awaiting_confirm',
  created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at     TIMESTAMP NOT NULL
);

-- === CONVERSATIONS ===
CREATE TABLE conversations (
  zalo_user_id     TEXT PRIMARY KEY,
  state            TEXT NOT NULL DEFAULT 'idle',
  pending_id       TEXT REFERENCES pending_confirmations(id),
  active_trip_id   TEXT REFERENCES trips(id),  -- NEW: trip context hiện tại
  last_active_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- === PROCESSED EVENTS ===
CREATE TABLE processed_events (
  event_id      TEXT PRIMARY KEY,
  processed_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- === SHEET OUTBOX ===
CREATE TABLE sheet_outbox (
  id            TEXT PRIMARY KEY,
  trip_id       TEXT NOT NULL REFERENCES trips(id),  -- NEW: biết sheet nào
  op            TEXT NOT NULL,
  payload_json  TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending',
  attempts      INTEGER NOT NULL DEFAULT 0,
  last_error    TEXT,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processed_at  TIMESTAMP
);

-- === AUDIT LOG ===
CREATE TABLE audit_log (
  id            TEXT PRIMARY KEY,
  ts            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  trip_id       TEXT REFERENCES trips(id),  -- NEW: scope theo trip
  actor_id      TEXT,
  action        TEXT NOT NULL,
  entity_id     TEXT,
  details_json  TEXT,
  trace_id      TEXT
);

CREATE INDEX idx_audit_trip ON audit_log(trip_id);
CREATE INDEX idx_audit_trace ON audit_log(trace_id);

-- Indexes khác (giữ từ v2.2)
CREATE INDEX idx_expenses_trip       ON expenses(trip_id, status);
CREATE INDEX idx_contributions_trip  ON contributions(trip_id, status);
CREATE INDEX idx_contributions_link  ON contributions(linked_expense_id) 
                                     WHERE linked_expense_id IS NOT NULL;
CREATE INDEX idx_pending_expires     ON pending_confirmations(expires_at);
CREATE INDEX idx_outbox_pending      ON sheet_outbox(status, created_at) 
                                     WHERE status = 'pending';
```

### 4.2. Google Sheet (1 per trip)

**Template sheet** (setup 1 lần ở Phase 0):
- Tạo Sheet tên `TripTreasurer - TEMPLATE`
- 3 tab rỗng: `Chi tiêu`, `Nạp quỹ & Ứng tiền`, `Tổng kết`
- Ghi `GOOGLE_SHEET_TEMPLATE_ID` vào `.env`
- Tạo folder `TripTreasurer Sheets` trên Drive, ghi `GOOGLE_SHEET_PARENT_FOLDER_ID`
- Share folder với service account (quyền Editor)

**Khi tạo trip mới:**

```python
async def provision_sheet_for_trip(trip: Trip) -> tuple[str, str]:
    # 1. Copy template sheet
    new_sheet = drive.files().copy(
        fileId=config.template_sheet_id,
        body={
            'name': f"Trip {trip.name} {trip.start_date}",
            'parents': [config.parent_folder_id]
        }
    ).execute()
    
    # 2. Ghi header (dùng batchUpdate, tránh quá nhiều API call)
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=new_sheet['id'],
        body={'data': [...]}  # header cho 3 tab
    ).execute()
    
    # 3. Lấy URL
    sheet_url = f"https://docs.google.com/spreadsheets/d/{new_sheet['id']}/edit"
    
    return new_sheet['id'], sheet_url
```

**Retry + fallback**: nếu provision thất bại, trip vẫn được tạo (DB commit), chỉ là `sheet_id=NULL`. Admin có lệnh `/trip_provision_sheet <trip_id>` để retry sau. Xem `RELIABILITY_SECURITY.md` section A.3.

---

## 5. Agent Core — logic chi tiết

### 5.1. Intent classifier (v2.3 — thêm multi-trip intents)

```
Input tin nhắn →
  ├─ Ảnh                                                    → log_expense_image
  │
  ├─ "/trip_new ..."                                        → trip_new
  ├─ "/trips"                                               → trip_list  (NEW v2.3)
  ├─ "/trip_view <id>"                                      → trip_view  (NEW v2.3)
  ├─ "/trip_switch <id>"                                    → trip_switch (NEW v2.3)
  ├─ "/trip_archive <id>" | "/trip_export <id>"             → trip_admin_command
  ├─ "/trip_status | /trip_remind | /trip_cancel | ...",    → trip_admin_command
  ├─ "/quy | /tongket | /cuatoi | /nap_cua_toi | /chiaai"   → query_command
  ├─ "/huy | /huy_auto | /rebuild_sheet | /xoadulieu"       → action_command
  ├─ "/help | /help <topic> | /lenh | /share"               → help_*
  │
  ├─ Có "ứng" + ("để chi|để trả|để góp|cho") + số tiền      → log_advance_expense
  │
  ├─ <tên> + ("đã nạp"|"góp") + số tiền
  │  (trong trip state=COLLECTING_TOPUP)                    → log_initial_topup
  │
  ├─ ("nạp"|"góp") + số tiền (không có "để")                → log_topup
  │
  ├─ ("chi"|"trả") + số tiền                                → log_expense
  │
  ├─ Chỉ có số tiền + nội dung                              → log_expense (mặc định)
  │
  ├─ State=AWAITING_CONFIRM → confirm / amend / cancel
  │
  ├─ Natural language help keywords                         → help_overview
  │
  ├─ User mới chưa có trong members                         → welcome
  │
  └─ Còn lại → LLM classify / fallback suggest
```

### 5.2-5.9. Parser rules + fuzzy match + help system

(Giữ nguyên từ v2.2. Xem v2.2 section 5.2-5.10 đầy đủ.)

### 5.10. Help system

Trigger qua `/help`, `/help <topic>`, `/lenh`, `/share`, ngôn ngữ tự nhiên. Content trong `app/help/*.md`. Xem [HELP_CONTENT.md](./HELP_CONTENT.md) đầy đủ.

### 5.11. Trip resolution logic (NEW v2.3)

Mỗi lần user gõ tin cần ghi data (expense, topup, advance), bot phải biết ghi vào trip nào:

```python
async def resolve_trip_context(zalo_user_id: str) -> TripContext:
    """
    Trả về trip mà user đang làm việc, hoặc raise để xử lý.
    """
    # 1. Tìm conversations.active_trip_id nếu đã set
    conv = await db.fetch_conversation(zalo_user_id)
    if conv.active_trip_id:
        trip = await db.fetch_trip(conv.active_trip_id)
        # Validate: trip vẫn đang active và user vẫn là member
        if trip.status == 'active' and await is_trip_member(trip.id, zalo_user_id):
            return TripContext(trip=trip, user_member=...)
        else:
            # Stale — clear và fallback
            conv.active_trip_id = None
    
    # 2. Tìm member của user
    member = await db.fetch_member_by_zalo(zalo_user_id)
    if member is None:
        raise UserNotRegisteredError()
    
    # 3. Tìm các trip ACTIVE mà member tham gia
    active_trips = await db.fetch_active_trips_for_member(member.id)
    
    if len(active_trips) == 0:
        # Case B: không có trip active
        raise NoActiveTripError(member)
    
    if len(active_trips) == 1:
        # Case A: happy path
        trip = active_trips[0]
        await db.update_conversation_active_trip(zalo_user_id, trip.id)
        return TripContext(trip=trip, user_member=member)
    
    # Case C (MVP không cho): 2+ active trip → hỏi user
    # Trong MVP, raise NotImplementedError hoặc chặn từ lúc tạo
    raise MultipleActiveTripsError(active_trips)
```

**MVP guard:** `/trip_new` sẽ reject nếu admin đã có trip ACTIVE khác trong vai trò admin, hoặc member được add đang có trip ACTIVE. Dialog rõ ràng:

```
⚠️ Không thể tạo chuyến mới.
Bạn đang là admin của chuyến đang hoạt động:
   • Hạ Long (đang ACTIVE)

Vui lòng kết chuyến cũ (`/trip_end`) trước khi tạo mới.
```

Exception duy nhất cho phép: trip mới ở state `COLLECTING_TOPUP` (chưa ACTIVE) khi chưa kết trip cũ. Lý do: tạo trip trước vài tuần là usecase thực tế.

### 5.12. Member reuse logic (NEW v2.3)

Khi admin khai `/trip_new ... gồm đức hà long minh an`:

```python
async def resolve_members_for_trip(
    admin_id: str,
    names: list[str]
) -> list[MemberResolution]:
    """
    Trả về list, mỗi entry: ('existing', member) or ('new', placeholder).
    Raise AmbiguousNameError nếu có tên match 2+ member.
    """
    resolutions = []
    names_in_current_trip = set()
    
    for name in names:
        # Validate unique trong trip
        if normalize_vn(name.lower()) in names_in_current_trip:
            raise DuplicateNameInTripError(name)
        names_in_current_trip.add(normalize_vn(name.lower()))
        
        # Search DB
        matches = await db.fetch_members_by_display_name(name, active=True)
        
        if len(matches) == 0:
            # Tạo placeholder
            placeholder = await db.create_member(
                display_name=capitalize_vn(name),
                zalo_user_id=None
            )
            resolutions.append(('new', placeholder))
            
        elif len(matches) == 1:
            resolutions.append(('existing', matches[0]))
            
        else:
            # Ambiguous — raise để orchestrator hỏi admin
            raise AmbiguousNameError(name, matches)
    
    return resolutions
```

**Xử lý ambiguous**: orchestrator bắt exception, render card hỏi admin chọn. Sau khi admin trả lời → resume với selection.

### 5.13. Sheet provisioning (NEW v2.3)

Khi trip tạo (confirmed từ state DRAFT → COLLECTING_TOPUP), bot provision sheet:

```python
async def on_trip_created(trip: Trip):
    # Retry logic: nếu fail, lưu vào sheet_outbox để retry sau
    try:
        sheet_id, sheet_url = await provision_sheet_for_trip(trip)
        trip.sheet_id = sheet_id
        trip.sheet_url = sheet_url
        await db.update_trip(trip)
    except GoogleSheetError as e:
        # Log + outbox
        await db.insert_sheet_outbox(
            trip_id=trip.id,
            op='provision_sheet',
            payload={'trip_id': trip.id}
        )
        # Admin vẫn tiếp tục được với trip, sheet sẽ tự tạo sau
        logger.warning("Sheet provision failed, queued for retry", extra={'trip_id': trip.id})
```

### 5.14. Thuật toán settlement + trip lifecycle state machine + fuzzy match

(Giữ nguyên từ v2.2.)

**State machine trip (mở rộng):**

```
(null)─[/trip_new]→ DRAFT ─[ok xác nhận]→ COLLECTING_TOPUP ─[đủ N/N nạp+"khởi động"]→ ACTIVE
                    │                                                                   │
                    │[huỷ]                              [/trip_cancel]                   │[/trip_end]
                    ▼                                     ▼                              ▼
                (xóa cứng)                        CANCELLED                           SETTLED
                                                  (soft delete)                          │
                                                                                         │[30 ngày]
                                                                                         ▼
                                                                                      ARCHIVED
```

### 5.15. Backup procedures (NEW v2.3)

Xem chi tiết trong [RELIABILITY_SECURITY.md](./RELIABILITY_SECURITY.md) section F.

**Tóm tắt:**
- Daily: `scripts/backup_db.sh` dump SQLite → `.sql.gz` local
- Weekly: `scripts/backup_offsite.sh` encrypt + upload Google Drive
- Quarterly: `scripts/test_restore.sh` test restore từ backup

### 5.16. Data retention policy (NEW v2.3)

| Loại dữ liệu | Giữ bao lâu | Action khi hết hạn |
|---|---|---|
| `trips`, `expenses`, `contributions` status=active hoặc settled | Vĩnh viễn | — |
| `trips` status=archived | Vĩnh viễn | — |
| `trips` status=cancelled | 90 ngày | HARD DELETE + cascade expenses/contribs |
| `audit_log` | 2 năm | Archive ra file, xoá khỏi DB |
| `sheet_outbox` status=done | 30 ngày | Delete |
| `pending_confirmations` expired | 24h sau expire | Delete |
| `processed_events` | 90 ngày | Delete (idempotency window đủ lớn) |
| Ảnh bill trên disk | Xoá ngay sau OCR | — |
| Backup local | 7 daily + 4 weekly + 12 monthly | Oldest bị thay thế |
| Backup offsite | Vĩnh viễn trên Drive | User quyết định xoá |

Cron job hàng ngày: `scripts/cleanup.py` thực hiện các action trên.

Admin có lệnh `/trip_purge <trip_id>` để hard delete ngay (confirm 2 lần) — dùng cho GDPR-like request.

---

## 6. Bảo mật

Tổng quan ở đây. Chi tiết đầy đủ (input validation layers, output filter, permission boundaries, rate limit, prompt injection defense) xem [RELIABILITY_SECURITY.md](./RELIABILITY_SECURITY.md) Section B.

### 6.1. Quick checklist

- [ ] Verify Zalo webhook signature
- [ ] Whitelist `oa_id`, `zalo_user_id` từ members.active
- [ ] Admin decorator `@require_admin`
- [ ] Google service account Editor-only (không Owner)
- [ ] Secret trong env, `.env` gitignored, pre-commit `detect-secrets`
- [ ] Refresh Zalo token every 90 ngày
- [ ] Input validation Pydantic + length limit + prompt injection regex
- [ ] Output filter JSON schema + content safety
- [ ] Sheet ghi `valueInputOption=RAW`
- [ ] SQL prepared statement
- [ ] DB role: reader / writer / admin tách biệt
- [ ] Ảnh MIME check, size ≤ 10MB, strip EXIF
- [ ] Rate limit per user / per OA
- [ ] Circuit breaker per external service
- [ ] Trip isolation: member của trip A không query được data trip B

---

## 7. Kế hoạch triển khai — 5 phase

### Phase 0 — Chuẩn bị hạ tầng (1-2 ngày)

1. Đăng ký Zalo OA tại https://oa.zalo.me
2. Tạo App Zalo Developer Portal, link OA, lấy credentials
3. Apply quyền nhận/gửi text & image — đợi duyệt 1-7 ngày
4. Google Cloud Project → Sheets API + **Drive API** (NEW cho copy template) → service account → JSON key
5. **Tạo Sheet template** (3 tab rỗng với header), ghi `GOOGLE_SHEET_TEMPLATE_ID`
6. **Tạo Drive folder** cho trips, share service account, ghi `GOOGLE_SHEET_PARENT_FOLDER_ID`
7. Setup repo git trên server Đức, Python 3.11 venv, `uv`
8. `.env` + `.env.example` (có thêm 2 ID trên)
9. Smoke test: Python script copy template thành sheet mới
10. Smoke test LLM Viettel
11. Setup Drive folder cho backup offsite, ghi `BACKUP_DRIVE_FOLDER_ID`

**Done khi:**
- [ ] Đủ secret
- [ ] Python copy Sheet template OK
- [ ] LLM Viettel OK
- [ ] Zalo OA submit duyệt

### Phase 1 — Core logic & test local với Claude (6-7 ngày)

**Repo skeleton (mở rộng v2.3):**

```
travel-expense-agent/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── channels/
│   │   ├── base.py
│   │   ├── zalo.py
│   │   └── mock.py
│   ├── agent/
│   │   ├── orchestrator.py
│   │   ├── state.py
│   │   ├── intents.py
│   │   ├── trip_resolver.py           # NEW v2.3
│   │   └── nodes/
│   │       ├── parse_trip_new.py
│   │       ├── parse_expense.py
│   │       ├── parse_advance_expense.py
│   │       ├── parse_topup.py
│   │       ├── parse_initial_topup.py
│   │       ├── parse_image.py
│   │       ├── confirm.py
│   │       ├── commit_trip.py
│   │       ├── commit_expense.py
│   │       ├── commit_advance_expense.py
│   │       ├── commit_topup.py
│   │       ├── commit_initial_topup.py
│   │       ├── help.py
│   │       ├── trip_list.py           # NEW v2.3
│   │       ├── trip_view.py           # NEW v2.3
│   │       └── query.py
│   ├── domain/
│   │   ├── models.py
│   │   ├── fund.py
│   │   ├── settlement.py
│   │   ├── fuzzy_match.py
│   │   └── member_resolver.py         # NEW v2.3
│   ├── storage/
│   │   ├── db.py
│   │   └── repositories/
│   ├── tools/
│   │   ├── llm.py
│   │   ├── ocr.py
│   │   ├── sheets.py
│   │   ├── sheet_provisioner.py       # NEW v2.3 (Drive copy)
│   │   └── sheet_projector.py
│   ├── reliability/                   # NEW v2.3
│   │   ├── retry.py                   # tenacity configs
│   │   ├── circuit_breaker.py
│   │   └── timeouts.py
│   ├── security/                      # NEW v2.3
│   │   ├── input_validation.py
│   │   ├── output_filter.py
│   │   ├── prompt_injection.py
│   │   └── permissions.py
│   ├── observability/                 # NEW v2.3
│   │   ├── tracing.py                 # OpenTelemetry setup
│   │   ├── metrics.py                 # Prometheus
│   │   └── logging.py                 # structlog
│   ├── help/                          # 9 .md files (xem HELP_CONTENT.md)
│   └── utils/
│       ├── vn_time.py
│       ├── money.py
│       └── idempotency.py
├── tests/
│   ├── test_parse_*.py
│   ├── test_fund.py
│   ├── test_settlement.py
│   ├── test_fuzzy_match.py
│   ├── test_trip_resolver.py          # NEW v2.3
│   ├── test_member_resolver.py        # NEW v2.3
│   ├── test_input_validation.py       # NEW v2.3
│   ├── test_retry.py                  # NEW v2.3
│   ├── test_circuit_breaker.py        # NEW v2.3
│   └── test_e2e_mock.py
├── evals/                             # NEW v2.3 (parser eval pipeline)
│   ├── golden_dataset.json
│   └── run_eval.py
├── scripts/
│   ├── backup_db.sh                   # NEW v2.3
│   ├── backup_offsite.sh              # NEW v2.3
│   ├── restore_db.py                  # NEW v2.3
│   ├── test_restore.sh                # NEW v2.3
│   ├── cleanup.py                     # NEW v2.3 (retention enforcement)
│   ├── refresh_zalo_token.py
│   └── seed_template_sheet.py         # NEW v2.3
├── alembic/
├── docs/
│   ├── runbook.md
│   ├── architecture.md
│   └── incident_response.md
├── .env.example
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── README.md
```

**Thứ tự code:**
1. `domain/fund.py` + `domain/settlement.py` + `domain/fuzzy_match.py` + `domain/member_resolver.py` + unit test
2. `storage/` schema + repositories + test in-memory
3. `reliability/` + `security/` + `observability/` foundation
4. `tools/llm.py` + `tools/sheets.py` + `tools/sheet_provisioner.py`
5. `agent/nodes/parse_*.py` từng cái có test + eval
6. `help/` content loader
7. `agent/trip_resolver.py` + test multi-trip scenarios
8. `agent/orchestrator.py` ráp nodes
9. `channels/mock.py` endpoint
10. Test với Claude

**Done khi tất cả 40+ E2E scenarios section 8.3 pass.**

### Phase 2 — Tích hợp Zalo (2-3 ngày)

(Giữ như v2.2 + thêm: provision sheet test với Drive API thật)

### Phase 3 — Hardening & mở nhóm (3-5 ngày)

1. Tick hết checklist section 6 + RELIABILITY_SECURITY checklist đầy đủ
2. Setup tracing + metric export
3. Setup backup cron (`scripts/backup_*.sh` trong crontab)
4. Test restore procedure
5. Eval pipeline chạy trong CI
6. Load test
7. Chaos test (kill LLM, Sheet 503, simulate Zalo timeout)

### Phase 4 — Chìa API + multi-trip nâng cao (tuỳ chọn)

REST API, MCP server, cho phép 1 user thuộc 2+ active trip.

---

## 8. Testing strategy

### 8.1. Các loại test

(Giữ từ v2.2.)

### 8.2. Test dataset (≥ 80 case)

(Giữ 60 case v2.2 + thêm 20 case multi-trip:)

```
# Trip lifecycle
"/trip_new Đà Lạt, 10-12/05, 5 người gồm đức hà long minh an, 800k"
"/trip_new Sapa, 20-22/5, 3 người"  # thiếu tên
"/trips"
"/trip_view TRIP-20260415"
"/trip_switch TRIP-20260510"
"/trip_archive TRIP-20260415"
"/trip_export TRIP-20260415"
"/trip_purge TRIP-20260415"

# Member reuse scenarios
# (Sẵn Hà, Long trong DB từ trip cũ)
"/trip_new Đà Lạt, ..., 3 người gồm đức hà long, 500k"
   → expect: reuse Hà, Long; không tạo placeholder

# Ambiguous name
# (Sẵn 2 Hà trong DB)
"/trip_new Nha Trang, ..., 3 người gồm đức hà minh, 500k"
   → expect: bot hỏi chọn Hà nào
```

### 8.3. E2E scenarios (40+ test cùng Claude)

**Tất cả scenarios v2.2 (33 scenarios) +**

**Multi-trip scenarios (NEW v2.3):**
34. Tạo trip mới với 4 member cũ (toàn bộ đã có trong DB) → không tạo placeholder, ping trực tiếp
35. Tạo trip với 3 cũ + 1 mới → 3 ping trực tiếp, 1 chờ nhắn
36. Ambiguous name (2 Hà trong DB) → bot hỏi admin chọn
37. `/trips` liệt kê đúng active/settled/archived
38. `/trip_view TRIP-xxx` show đúng data
39. `/trip_switch` (khi user có 2 trip) set active_trip_id đúng
40. Auto archive sau 30 ngày SETTLED (test với mock time)
41. Data isolation: user trip A không query được expense trip B
42. `/trip_export TRIP-xxx` → CSV đúng format
43. Tạo trip mới khi đang có trip ACTIVE ở vai admin → reject
44. Tạo trip khi admin có trip ở COLLECTING_TOPUP → OK (exception case)
45. Sheet provisioning: trip mới có sheet_id được set
46. Sheet provisioning fail → trip vẫn tạo, outbox queue retry
47. `/rebuild_sheet TRIP-xxx` rebuild từ DB

### 8.4. Invariant tests

Sau mỗi commit:
```python
assert fund_balance(trip_id) >= 0
assert sum(nets.values()) == fund_remain
assert all(c.linked_expense_id for c in contribs if kind in (advance, auto_advance))
assert all(c.linked_expense_id IS NULL for c in contribs if kind in (initial_topup, extra_topup))
assert trip_state_transitions_valid()
assert expense.trip_id == contribution.trip_id (khi linked)  # NEW
assert trip.sheet_id IS NOT NULL when trip.status IN (active, settled)  # NEW (hoặc có outbox pending)
assert each member has at most 1 ACTIVE trip (MVP guard)  # NEW
```

---

## 9. Observability & Ops

(Chi tiết đầy đủ trong [RELIABILITY_SECURITY.md](./RELIABILITY_SECURITY.md) Section C.)

Tóm tắt quick reference:

### 9.1. Logging

structlog JSON; mỗi log có `trace_id`, `trip_id` (nếu có), `zalo_user_id`, `member_id`, `event`, `duration_ms`.

### 9.2. Metrics

Prometheus, bao gồm business metrics (trips created, fund balance gauge), cost metrics (LLM tokens, Sheet API calls), reliability metrics (circuit breaker state, retry count).

### 9.3. Tracing

OpenTelemetry per-request trace, span per node (parse → LLM → DB → Sheet).

### 9.4. Alerts

10+ rule bao gồm: Sheet error rate, LLM latency, outbox pending, backup failure, trip stuck.

### 9.5. Runbook + Incident response

Xem `docs/runbook.md` và `docs/incident_response.md`.

---

## 10. Rủi ro & biện pháp

(Giữ 12 rủi ro v2.2 + thêm 5:)

| Rủi ro | XS | Tác động | Biện pháp |
|---|---|---|---|
| Member duplicate display_name gây ambiguous | Trung | Trung | Ambiguous handler hỏi admin; audit log đầy đủ |
| Trip data cross-contamination | Thấp | Cao | Query luôn có `WHERE trip_id`; test isolation; code review |
| Sheet provisioning fail → trip không có sheet | Thấp | Trung | Outbox retry; `/trip_provision_sheet` admin |
| User switch trip nhầm ghi expense vào trip cũ | Thấp | Trung | UI confirm show rõ trip name; audit log |
| Backup script fail âm thầm | Thấp | Cao | Alert khi > 25h không có backup mới |
| Trip ARCHIVED vẫn cho ghi được | Thấp | Trung | Guard ở commit layer, test invariant |

---

## 11. Checklist đã chốt (v2.3)

(Giữ từ v2.2 + thêm:)

- [x] Multi-trip first-class: member reuse, trip isolation
- [x] 1 Google Sheet per trip, provision từ template
- [x] 1 ACTIVE trip per user tại 1 thời điểm (MVP)
- [x] Backup offsite lên Google Drive
- [x] Data retention policy rõ ràng (section 5.16)
- [x] Auto archive sau 30 ngày SETTLED
- [x] Ambiguous name handler
- [x] `/trips`, `/trip_view`, `/trip_switch`, `/trip_archive`, `/trip_export`, `/trip_purge`
- [x] Phụ lục `RELIABILITY_SECURITY.md` đầy đủ

---

## 12. Phụ lục

### 12.1. Zalo OA endpoints
(Giữ từ v2.2)

### 12.2. LLM Viettel Netmind
(Giữ từ v2.2)

### 12.3. Google Drive API (NEW v2.3)
```python
from googleapiclient.discovery import build

drive = build('drive', 'v3', credentials=creds)

# Copy template
new_file = drive.files().copy(
    fileId=TEMPLATE_ID,
    body={'name': 'New Sheet Name', 'parents': [FOLDER_ID]}
).execute()
```

### 12.4. Matrix 5 intent parse
(Giữ từ v2.2)

### 12.5. Công thức quỹ
(Giữ từ v2.2)

### 12.6. Regex helpers
(Giữ từ v2.2)

### 12.7. Data retention bảng tra cứu
(Xem section 5.16)

### 12.8. Config `.env.example` đầy đủ

```bash
# ===== Zalo OA =====
ZALO_APP_ID=
ZALO_APP_SECRET=
ZALO_OA_ID=
ZALO_OA_ACCESS_TOKEN=
ZALO_OA_REFRESH_TOKEN=
ZALO_WEBHOOK_SECRET=

# ===== LLM =====
LLM_PROVIDER=viettel
LLM_BASE_URL=https://netmind.viettel.vn/codev
LLM_API_KEY=
LLM_MODEL=openai/gpt-oss-120b
LLM_TIMEOUT_SECONDS=15

# ===== Google =====
GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/service-account.json
GOOGLE_SHEET_TEMPLATE_ID=               # Sheet template để copy
GOOGLE_SHEET_PARENT_FOLDER_ID=          # Folder chứa các sheet trip
BACKUP_DRIVE_FOLDER_ID=                 # Folder chứa backup

# ===== DB =====
DATABASE_URL=sqlite:////data/agent.db

# ===== Agent =====
ADMIN_MEMBER_IDS=M001                   # Đức
TIMEZONE=Asia/Ho_Chi_Minh
RATE_LIMIT_PER_USER_PER_MIN=30
RATE_LIMIT_PER_USER_PER_DAY=500
CIRCUIT_BREAKER_THRESHOLD=5
CIRCUIT_BREAKER_COOLDOWN_SECONDS=300

# ===== Observability =====
LOG_LEVEL=INFO
OTEL_EXPORTER=console                    # hoặc jaeger
PROMETHEUS_PORT=9090

# ===== Backup =====
BACKUP_LOCAL_PATH=/data/backups
BACKUP_ENCRYPTION_KEY_PATH=/secrets/backup-gpg.key
BACKUP_RETENTION_DAILY=7
BACKUP_RETENTION_WEEKLY=4
BACKUP_RETENTION_MONTHLY=12
```

---

**Hết plan v2.3.**

**Xem 2 file đi kèm để có bức tranh đầy đủ:**
- [HELP_CONTENT.md](./HELP_CONTENT.md) — 9 help files
- [RELIABILITY_SECURITY.md](./RELIABILITY_SECURITY.md) — Production-grade spec đầy đủ

**Sẵn sàng bắt đầu Phase 0 (hoặc Option C: build repo skeleton trong chat này rồi chuyển sang Claude Code).**
