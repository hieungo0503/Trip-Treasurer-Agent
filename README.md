# Trip Treasurer Agent 🧳💰

AI Agent quản lý chi tiêu du lịch nhóm qua **Zalo OA**, built với Python + FastAPI.

## Tài liệu plan

| File | Mô tả |
|---|---|
| `PLAN_v2.3.md` | Plan đầy đủ — kiến trúc, flow, DB schema, testing |
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
git clone <repo>
cd travel-expense-agent
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Cấu hình
cp .env.example .env
# Điền đầy đủ các giá trị trong .env

# 3. Chạy test để verify
pytest tests/ -v

# 4. Khởi động server local
uvicorn app.main:app --reload --port 8080
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
│   ├── main.py                    # FastAPI entry point
│   ├── config.py                  # Settings (pydantic-settings)
│   ├── agent/                     # Agent core (state machine)
│   │   ├── orchestrator.py        # TODO Phase 1
│   │   ├── intents.py             # TODO Phase 1
│   │   ├── trip_resolver.py       # TODO Phase 1
│   │   └── nodes/                 # Parse/commit nodes
│   ├── channels/
│   │   ├── zalo.py                # TODO Phase 2
│   │   └── mock.py                # TODO Phase 1 (test)
│   ├── domain/                    # ✅ Business logic (done)
│   │   ├── models.py              # Pydantic models
│   │   ├── fund.py                # Quỹ logic + invariants
│   │   ├── settlement.py          # Thuật toán chia tiền
│   │   ├── fuzzy_match.py         # Match tên tiếng Việt
│   │   └── member_resolver.py     # Resolve member khi tạo trip
│   ├── storage/                   # TODO Phase 1
│   ├── tools/                     # TODO Phase 1
│   ├── reliability/               # TODO Phase 1
│   ├── security/                  # TODO Phase 1
│   ├── observability/             # TODO Phase 1
│   ├── help/                      # TODO Phase 1 (copy từ HELP_CONTENT.md)
│   └── utils/                     # ✅ Utilities (done)
│       ├── money.py               # Parse/format tiền VNĐ
│       └── vn_time.py             # Timezone helper
├── tests/                         # ✅ 103 unit tests pass, coverage 87%
├── evals/                         # TODO Phase 1 (golden dataset)
├── scripts/                       # TODO Phase 3 (backup, refresh token)
├── alembic/                       # DB migration
├── docs/runbook.md                # TODO Phase 3
├── .env.example                   # Template cấu hình
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml
```

## Trạng thái hiện tại

| Layer | Trạng thái | Notes |
|---|---|---|
| Domain logic | ✅ Done | fund, settlement, fuzzy_match, member_resolver |
| Utils | ✅ Done | money parser, vn_time |
| Tests | ✅ 103/103 pass | Coverage 87.6% |
| Storage (DB) | 🚧 Phase 1 | SQLAlchemy + Alembic |
| Agent core | 🚧 Phase 1 | State machine, nodes, parsers |
| LLM integration | 🚧 Phase 1 | gpt-oss-120b via Viettel |
| Mock channel | 🚧 Phase 1 | Test local với Claude |
| Zalo integration | 🚧 Phase 2 | Webhook, send API |
| Google Sheets | 🚧 Phase 2 | Sheet projector |
| Security | 🚧 Phase 3 | Input validation, rate limit |
| Observability | 🚧 Phase 3 | Tracing, metrics |

## Test

```bash
# Chạy tất cả
pytest tests/ -v

# Với coverage
pytest tests/ --cov=app --cov-report=html

# Chỉ domain tests (nhanh, không cần external)
pytest tests/test_fund.py tests/test_settlement.py tests/test_fuzzy_match.py -v
```

## Tiếp tục với Claude Code

```bash
# Sau khi clone về server
cd travel-expense-agent
claude  # Mở Claude Code trong thư mục này

# Claude Code sẽ đọc PLAN_v2.3.md và tiếp tục Phase 1
```

## Tác giả & Context

- Admin: Đức (zalo admin của nhóm)
- LLM: openai/gpt-oss-120b via Viettel Netmind
- Plan version: v2.3
- Đọc đầy đủ: `PLAN_v2.3.md`
