# Trip Treasurer Agent 🧳💰

AI Agent quản lý chi tiêu du lịch nhóm qua **Zalo OA**, built với Python + FastAPI.

## Tài liệu plan

| File | Mô tả |
|---|---|
| `PLAN_v2.3.md` | Plan đầy đủ — kiến trúc, flow, DB schema, testing strategy, **tiến độ thực tế** |
| `HELP_CONTENT.md` | Nội dung 9 file help markdown cho bot |
| `RELIABILITY_SECURITY.md` | Retry, circuit breaker, security, tracing, backup |

## Yêu cầu hệ thống

- Python 3.11+
- SQLite (MVP) hoặc PostgreSQL (production)
- Docker + Docker Compose
- Zalo OA đã được duyệt
- Google Cloud service account (Sheets + Drive API)
- Server có HTTPS public URL cho Zalo webhook

## Setup nhanh (Development)

```bash
# 1. Clone và cài dependencies
git clone https://github.com/hieungo0503/Trip-Treasurer-Agent.git
cd Trip-Treasurer-Agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Cấu hình
cp .env.example .env
# Điền đầy đủ các giá trị trong .env

# 3. Chạy test để verify
pytest tests/ -v

# 4. Khởi động server local
uvicorn app.main:app --reload --port 8080

# 5. Test bot qua mock channel
curl -X POST http://localhost:8080/mock/send \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user001", "message": "/help"}'
```

## Chạy với Docker

```bash
cp .env.example .env
# Điền secret vào .env

mkdir -p data secrets

docker compose up -d
docker compose logs -f app
```

## Cấu trúc dự án

```
travel-expense-agent/
├── app/
│   ├── main.py                    # ✅ FastAPI entry point + lifespan
│   ├── config.py                  # ✅ Settings (pydantic-settings)
│   ├── agent/
│   │   ├── orchestrator.py        # ✅ Full pipeline Phase 1
│   │   ├── intents.py             # ✅ Intent classifier
│   │   ├── trip_resolver.py       # ✅ Trip context resolution
│   │   └── nodes/
│   │       ├── commit_expense.py      # ✅
│   │       ├── commit_topup.py        # ✅
│   │       ├── commit_advance_expense.py  # ✅
│   │       ├── commit_initial_topup.py    # ✅
│   │       └── commit_trip.py         # ✅
│   ├── channels/
│   │   ├── mock.py                # ✅ POST /mock/send (test local)
│   │   └── zalo.py                # 🔲 Phase 2
│   ├── domain/                    # ✅ Business logic (done)
│   │   ├── models.py
│   │   ├── fund.py                # Quỹ logic + invariants
│   │   ├── settlement.py          # Thuật toán chia tiền
│   │   ├── fuzzy_match.py         # Match tên tiếng Việt
│   │   └── member_resolver.py     # Resolve member khi tạo trip
│   ├── storage/                   # ✅ SQLite async + repos
│   ├── tools/
│   │   ├── llm.py                 # ✅ LLM + rule-based parsers
│   │   ├── ocr.py                 # 🔲 Stub Phase 1
│   │   ├── sheets.py              # 🔲 Stub Phase 1 (Phase 2 thật)
│   │   ├── sheet_provisioner.py   # 🔲 Stub Phase 1
│   │   └── sheet_projector.py     # ✅ Background loop
│   ├── reliability/               # ✅ Circuit breaker + retry
│   ├── security/                  # ✅ Input validation + permissions
│   ├── observability/             # ✅ Structlog + OTel + Prometheus
│   ├── help/                      # ✅ 9 file .md content
│   └── utils/                     # ✅ money, vn_time
├── tests/                         # ✅ 261 unit tests pass
├── evals/                         # 🔲 Phase 1 (parser eval pipeline)
├── scripts/                       # 🔲 Phase 3 (backup, cleanup)
├── alembic/                       # DB migration
├── .env.example
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml
```

## Trạng thái hiện tại (22/04/2026 — session 2)

| Layer | Trạng thái | Notes |
|---|---|---|
| Domain logic | ✅ Done | fund, settlement, fuzzy_match, member_resolver |
| Utils | ✅ Done | money parser, vn_time |
| Storage (DB) | ✅ Done | SQLite async, repositories đầy đủ |
| Reliability | ✅ Done | Circuit breaker, retry, timeouts |
| Security | ✅ Done | Input validation, permissions |
| Observability | ✅ Done | structlog, OpenTelemetry, Prometheus |
| LLM integration | ✅ Done | gpt-oss-120b via Viettel + rule fallback |
| Agent core | ✅ Done | Orchestrator + tất cả commit nodes Phase 1 |
| Mock channel | ✅ Done | POST /mock/send sẵn sàng test |
| Help system | ✅ Done | 9 file markdown + loader |
| Tests | ✅ 308/308 pass | Coverage 79.6% |
| E2E tests | ✅ Done | 35 scenarios qua mock channel |
| Zalo integration | 🔲 Phase 2 | Webhook, send API |
| Google Sheets (thật) | 🔲 Phase 2 | Drive copy template, append rows |
| Backup / cleanup scripts | 🔲 Phase 3 | backup_db.sh, cleanup.py, ... |
| Hardening | 🔲 Phase 3 | Rate limit, chaos test, alert rules |

Xem chi tiết tại phần **🟢 TIẾN ĐỘ THỰC TẾ** trong `PLAN_v2.3.md`.

## Test

```bash
# Chạy tất cả
pytest tests/ -v

# Với coverage
pytest tests/ --cov=app --cov-report=html

# Chỉ domain tests (nhanh, không cần external)
pytest tests/test_fund.py tests/test_settlement.py tests/test_fuzzy_match.py -v

# Test cụ thể
pytest tests/test_storage.py -v
pytest tests/test_circuit_breaker.py -v
```

## API Endpoints (Phase 1)

| Method | Path | Mô tả |
|---|---|---|
| POST | `/mock/send` | Test bot local (không cần Zalo) |
| GET | `/health` | Health check (DB + circuit breakers) |
| GET | `/metrics` | Prometheus metrics |
| POST | `/webhook/zalo` | Placeholder — Phase 2 |

### Ví dụ test local

```bash
# Welcome message
curl -s -X POST http://localhost:8080/mock/send \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","message":"xin chào"}' | python3 -m json.tool

# Tạo chuyến mới
curl -s -X POST http://localhost:8080/mock/send \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","message":"/trip_new Đà Lạt, 10-12/05, 4 người gồm đức hà long minh, 800k"}'

# Xác nhận
curl -s -X POST http://localhost:8080/mock/send \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","message":"ok"}'

# Ghi chi tiêu
curl -s -X POST http://localhost:8080/mock/send \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","message":"ăn sáng 150k"}'
```

## Git & Auto-commit

Repo: `https://github.com/hieungo0503/Trip-Treasurer-Agent.git`

Claude Code được cấu hình **tự động commit + push** sau mỗi session (Stop hook trong `.claude/settings.local.json`).

## Tác giả & Context

- Admin: Đức (zalo admin của nhóm)
- LLM: openai/gpt-oss-120b via Viettel Netmind
- Plan version: v2.3
- Đọc đầy đủ: `PLAN_v2.3.md`
