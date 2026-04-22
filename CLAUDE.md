# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Skills

Đọc skills trong thư mục `skills/` trước khi implement bất kỳ thứ gì:

- `skills/skills/trip-expense-domain/` — Đọc khi làm việc với domain logic,
  fund calculation, commit expense/contribution, viết tests
- `skills/skills/zalo-agent-patterns/` — Đọc khi implement webhook, intent
  classifier, message formatting, mock channel
- `skills/skills/reliability-security/` — Đọc khi viết external API calls
  hoặc security/validation code

## Plan

Xem `PLAN_v2.3.md` cho architecture tổng thể.
Xem `RELIABILITY_SECURITY.md` cho spec đầy đủ.

## Nguyên tắc bất di bất dịch

1. fund_balance >= 0 luôn luôn — assert sau mọi commit
2. advance/auto_advance KHÔNG tăng quỹ thực
3. Mọi query expenses/contributions phải có WHERE trip_id=?
4. Sheet ghi với valueInputOption=RAW (không USER_ENTERED)
5. Không bao giờ tự ghi DB mà không có user confirm (human-in-the-loop)

## Commands

```bash
# Install dependencies (dev)
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# Run tests with coverage
pytest tests/ --cov=app --cov-report=html

# Run a single test file
pytest tests/test_fund.py -v

# Run a single test by name
pytest tests/test_fund.py::test_fund_balance_invariant -v

# Run only fast domain tests (no external deps)
pytest tests/test_fund.py tests/test_settlement.py tests/test_fuzzy_match.py tests/test_member_resolver.py -v

# Lint
ruff check app/ tests/

# Type check
mypy app/

# Start dev server
uvicorn app.main:app --reload --port 8080

# Docker
docker compose up -d
docker compose logs -f app

# DB migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
```

## Architecture

### 4-Layer System

```
CHANNEL (Zalo OA / mock)
    ↓ HTTPS webhook (verify signature, return 200 < 2s)
API GATEWAY (FastAPI — app/main.py)
    ↓ async task queue
AGENT CORE (app/agent/)
    ├── intent_classify → resolve_trip_context → parse_node → confirm → commit_node
    ├── Per-user state: IDLE → AWAITING_CONFIRM → COMMITTED
    └── Per-trip state: DRAFT → COLLECTING_TOPUP → ACTIVE → SETTLED → ARCHIVED
    ↓
TOOLS & STORAGE
    ├── LLM: openai/gpt-oss-120b via Viettel Netmind
    ├── DB (SQLite/Postgres) — source of truth
    └── Google Sheets — per-trip view (rebuild-able from DB)
```

### Domain Logic (`app/domain/`) — Already Implemented

- `fund.py` — quỹ chung invariants, `compute_fund_balance`, `check_expense_against_fund`, `verify_fund_invariants`
- `settlement.py` — greedy minimum-transaction algorithm
- `fuzzy_match.py` — Vietnamese name matching (exact → normalized → Levenshtein ≤ 2)
- `member_resolver.py` — resolve member names when creating trips (reuse / placeholder / ambiguous)
- `models.py` — shared Pydantic models for all layers

### Fund Model (critical — different from Splitwise)

```
fund_balance = Σ contribution(initial_topup, extra_topup)
             − Σ expense WITHOUT linked contribution

advance / auto_advance do NOT increase fund_balance
— they cancel out with their linked expense
```

`contribution.created_at` (input order) determines fund state, not `occurred_at`.

### Trip Isolation

Every query on `expenses`, `contributions`, `audit_log`, `sheet_outbox` **must** include `WHERE trip_id = ?`. Missing this is a data-leak bug.

### DB Commit Pattern

Every commit: check fund → insert records → insert audit_log → insert sheet_outbox → assert invariants. If invariant fails, rollback. Sheet is updated asynchronously via outbox.

### What's Implemented vs TODO

| Component | Status |
|---|---|
| `app/domain/` | ✅ Done (103 tests, 87.6% coverage) |
| `app/utils/` (money, vn_time) | ✅ Done |
| `app/storage/` (DB + repos) | 🚧 Phase 1 |
| `app/agent/` (orchestrator, nodes) | 🚧 Phase 1 |
| `app/channels/mock.py` | 🚧 Phase 1 |
| `app/reliability/`, `app/security/`, `app/observability/` | 🚧 Phase 1 |
| `app/channels/zalo.py` | 🚧 Phase 2 |
| `app/tools/sheets.py` (Google Sheets) | 🚧 Phase 2 |
