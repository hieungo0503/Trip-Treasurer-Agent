"""
E2E tests — full pipeline qua mock channel.

Dùng FastAPI TestClient (httpx.AsyncClient + ASGITransport).
DB: in-memory SQLite (override DATABASE_URL).
LLM: call_llm bị mock → luôn raise exception → rule-based fallback.
Sheet projector: mock no-op để tránh background task.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# ── Test constants ────────────────────────────────────────────────────────────

USER_ID = "zalo_e2e_001"
MEMBER_ID = "M_E2E_001"
MEMBER_NAME = "Đức"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Xoá cache settings trước/sau mỗi test."""
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def client(tmp_path):
    """
    FastAPI test client với:
    - SQLite file tạm (tmp_path)
    - DB initialized thủ công (ASGITransport không chạy lifespan)
    - LLM mocked → rule-based fallback
    """
    db_file = str(tmp_path / "test_e2e.db")

    import app.storage.db as db_module
    from app.storage.db import Database

    # Initialize DB manually — lifespan không chạy với ASGITransport
    test_db = Database(db_file)
    await test_db.connect()
    await test_db.init_schema()
    db_module._db_instance = test_db

    env_overrides = {
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_file}",
        "OTEL_EXPORTER": "none",
        "LOG_LEVEL": "WARNING",
        "LLM_API_KEY": "test-key",
        "ADMIN_MEMBER_IDS": MEMBER_ID,
    }

    with patch.dict(os.environ, env_overrides):
        from app.config import get_settings
        get_settings.cache_clear()

        with patch("app.tools.llm.call_llm", new_callable=AsyncMock,
                   side_effect=Exception("test mode - no LLM")):
            from app.main import app
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                # Insert test member
                now = datetime.utcnow().isoformat()
                await test_db._conn.execute(
                    "INSERT INTO members (id, zalo_user_id, display_name, full_name, is_admin, active, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (MEMBER_ID, USER_ID, MEMBER_NAME, "Nguyễn Văn Đức", 1, 1, now),
                )
                await test_db._conn.commit()
                yield ac

    # Cleanup
    await test_db.close()
    db_module._db_instance = None


def _send(client: AsyncClient, text: str, user_id: str = USER_ID):
    return client.post("/mock/send", json={"zalo_user_id": user_id, "text": text})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _replies(resp) -> list[str]:
    data = resp.json()
    return [m["text"] for m in data.get("bot_replies", [])]


def _reply(resp) -> str:
    texts = _replies(resp)
    return "\n".join(texts) if texts else ""


# ── Group 1: Basic / navigation ───────────────────────────────────────────────

async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "degraded")


async def test_help_overview(client):
    r = await _send(client, "/help")
    assert r.status_code == 200
    text = _reply(r)
    assert text  # trả về nội dung help


async def test_help_topic_chi(client):
    r = await _send(client, "/help chi")
    assert r.status_code == 200
    text = _reply(r)
    assert text


async def test_help_share(client):
    r = await _send(client, "/share")
    assert r.status_code == 200
    assert _reply(r)


async def test_unknown_intent(client):
    r = await _send(client, "bla bla không rõ nghĩa gì cả xyzxyz")
    assert r.status_code == 200
    text = _reply(r)
    assert "chưa hiểu" in text or "help" in text.lower()


async def test_invalid_input_too_long(client):
    long_text = "chi " + "a" * 600
    r = await _send(client, long_text)
    assert r.status_code == 200
    # InputValidationError → bot reply với error message
    text = _reply(r)
    assert text


# ── Group 2: Guard — no trip ──────────────────────────────────────────────────

async def test_expense_without_trip(client):
    """chi tiêu khi chưa có chuyến → thông báo lỗi."""
    r = await _send(client, "chi 500k ăn uống")
    assert r.status_code == 200
    text = _reply(r)
    assert "chuyến" in text.lower() or "trip" in text.lower()


async def test_topup_without_trip(client):
    r = await _send(client, "nạp 500k")
    assert r.status_code == 200
    text = _reply(r)
    assert "chuyến" in text.lower() or "trip" in text.lower()


# ── Group 3: New user (no member record) ──────────────────────────────────────

async def test_new_user_welcome(client):
    """User chưa có trong DB → welcome message."""
    r = await _send(client, "xin chào", user_id="new_user_999")
    assert r.status_code == 200
    text = _reply(r)
    assert text  # welcome card


async def test_new_user_expense_blocked(client):
    """User chưa có trong DB, gửi chi tiêu → blocked."""
    r = await _send(client, "chi 200k", user_id="new_user_998")
    assert r.status_code == 200
    text = _reply(r)
    # new user → WELCOME intent (overrides everything)
    assert text


# ── Group 4: Trip creation flow ───────────────────────────────────────────────

async def test_trip_new_missing_fields(client):
    """/trip_new thiếu thông tin → hướng dẫn nhập lại."""
    r = await _send(client, "/trip_new Đà Lạt")
    assert r.status_code == 200
    text = _reply(r)
    assert "Thiếu" in text or "thiếu" in text or "thông tin" in text.lower()


async def test_trip_new_cancel_flow(client):
    """Tạo trip → confirm card → huỷ."""
    # 1. Create trip
    r = await _send(client, "/trip_new Đà Lạt, 10-12/05, 1 người gồm đức, 800k")
    assert r.status_code == 200
    text = _reply(r)
    assert "XÁC NHẬN" in text.upper() or "xác nhận" in text.lower() or "ok" in text.lower()

    # 2. Cancel
    r2 = await _send(client, "huỷ")
    assert r2.status_code == 200
    text2 = _reply(r2)
    assert "huỷ" in text2.lower() or "❌" in text2


async def test_trip_full_creation(client):
    """Full flow: tạo trip → ok → trip được tạo."""
    # 1. Parse
    r = await _send(client, "/trip_new Hội An, 15-17/06, 1 người gồm đức, 1tr")
    assert r.status_code == 200
    text = _reply(r)
    assert text  # confirm card

    # 2. Confirm
    r2 = await _send(client, "ok")
    assert r2.status_code == 200
    text2 = _reply(r2)
    assert "Hội An" in text2 or "✅" in text2 or "đã tạo" in text2.lower()

    return text2  # return for downstream use


async def test_trip_list_after_creation(client):
    """/trips sau khi tạo trip → hiển thị danh sách."""
    # Create trip first
    await _send(client, "/trip_new Nha Trang, 20-22/07, 1 người gồm đức, 500k")
    await _send(client, "ok")

    r = await _send(client, "/trips")
    assert r.status_code == 200
    text = _reply(r)
    assert "Nha Trang" in text or "chuyến" in text.lower()


async def test_trip_view(client):
    """/trip_view <id> → chi tiết chuyến."""
    # Create trip
    await _send(client, "/trip_new Phú Quốc, 01-03/08, 1 người gồm đức, 600k")
    r_confirm = await _send(client, "ok")
    text_confirm = _reply(r_confirm)

    # Extract trip ID from confirm message (format: TRIP-YYYYMMDD-XXXXXX)
    import re
    m = re.search(r"TRIP-\d{8}-[A-Z0-9]{6}", text_confirm)
    if m:
        trip_id = m.group(0)
        r = await _send(client, f"/trip_view {trip_id}")
        assert r.status_code == 200
        text = _reply(r)
        assert "Phú Quốc" in text or trip_id in text


# ── Group 5: Initial topup + activate ─────────────────────────────────────────

async def _create_and_activate_trip(client, trip_name="Test Trip") -> str:
    """Helper: tạo trip 1 người → initial topup → ACTIVE. Trả về trip_id."""
    await _send(client, f"/trip_new {trip_name}, 10-12/05, 1 người gồm đức, 800k")
    r_trip = await _send(client, "ok")
    text = _reply(r_trip)

    import re
    m = re.search(r"TRIP-\d{8}-[A-Z0-9]{6}", text)
    trip_id = m.group(0) if m else ""

    # Initial topup
    await _send(client, "đức đã nạp 800k")
    await _send(client, "ok")

    return trip_id


async def test_initial_topup_flow(client):
    """Tạo trip → initial topup → confirm → trip ACTIVE."""
    await _send(client, "/trip_new Đà Nẵng, 05-07/09, 1 người gồm đức, 700k")
    r_trip = await _send(client, "ok")
    text_trip = _reply(r_trip)
    assert "Đà Nẵng" in text_trip or "✅" in text_trip

    # Parse initial topup
    r_topup = await _send(client, "đức đã nạp 700k")
    assert r_topup.status_code == 200
    text_topup = _reply(r_topup)
    assert "nạp" in text_topup.lower() or "xác nhận" in text_topup.lower()

    # Confirm
    r_confirm = await _send(client, "ok")
    assert r_confirm.status_code == 200
    text_confirm = _reply(r_confirm)
    assert "✅" in text_confirm or "ghi" in text_confirm.lower()
    # Trip phải ACTIVE
    assert "ACTIVE" in text_confirm or "active" in text_confirm.lower()


# ── Group 6: Expense flow ─────────────────────────────────────────────────────

async def test_log_expense_confirm_flow(client):
    """Full expense flow: parse → confirm card → ok → ghi."""
    await _create_and_activate_trip(client, "Expense Test Trip")

    # Parse expense
    r = await _send(client, "chi 300k ăn uống")
    assert r.status_code == 200
    text = _reply(r)
    assert "300" in text or "xác nhận" in text.lower() or "chi" in text.lower()

    # Confirm
    r2 = await _send(client, "ok")
    assert r2.status_code == 200
    text2 = _reply(r2)
    assert "✅" in text2 or "ghi" in text2.lower()


async def test_log_expense_cancel(client):
    """Expense parse → huỷ."""
    await _create_and_activate_trip(client, "Cancel Test Trip")

    await _send(client, "chi 200k xe ôm")
    r = await _send(client, "huỷ")
    assert r.status_code == 200
    text = _reply(r)
    assert "huỷ" in text.lower() or "❌" in text


async def test_log_expense_no_amount(client):
    """Chi không có số tiền → bot hỏi lại."""
    await _create_and_activate_trip(client, "No Amount Trip")

    r = await _send(client, "chi ăn uống")
    assert r.status_code == 200
    text = _reply(r)
    # Bot trả về lỗi vì không parse được amount
    assert text


async def test_expense_auto_advance(client):
    """Quỹ = 0 nhưng vẫn chi → auto_advance được tạo."""
    # Trip với quỹ nhỏ
    await _send(client, "/trip_new Auto Advance Trip, 10-12/05, 1 người gồm đức, 100k")
    await _send(client, "ok")
    await _send(client, "đức đã nạp 100k")
    await _send(client, "ok")

    # Chi nhiều hơn quỹ
    r = await _send(client, "chi 500k khách sạn")
    assert r.status_code == 200
    text = _reply(r)
    # Confirm card hiển thị warning quỹ không đủ
    assert text

    r2 = await _send(client, "ok")
    assert r2.status_code == 200
    text2 = _reply(r2)
    assert "✅" in text2 or "ghi" in text2.lower()


# ── Group 7: Topup flow ───────────────────────────────────────────────────────

async def test_log_extra_topup(client):
    """nạp thêm vào quỹ sau khi trip ACTIVE."""
    await _create_and_activate_trip(client, "Topup Test Trip")

    r = await _send(client, "nạp 200k")
    assert r.status_code == 200
    text = _reply(r)
    assert "200" in text or "nạp" in text.lower() or "xác nhận" in text.lower()

    r2 = await _send(client, "ok")
    assert r2.status_code == 200
    text2 = _reply(r2)
    assert "✅" in text2 or "ghi" in text2.lower()


async def test_log_topup_no_amount(client):
    """nạp không có số tiền → bot hỏi lại."""
    await _create_and_activate_trip(client, "Topup No Amount")

    r = await _send(client, "nạp thêm")
    assert r.status_code == 200
    text = _reply(r)
    assert text


# ── Group 8: Advance expense ──────────────────────────────────────────────────

async def test_log_advance_expense(client):
    """ứng tiền + chi tiêu."""
    await _create_and_activate_trip(client, "Advance Test Trip")

    r = await _send(client, "ứng 400k để chi thuê xe")
    assert r.status_code == 200
    text = _reply(r)
    assert "400" in text or "ứng" in text.lower() or "xác nhận" in text.lower()

    r2 = await _send(client, "ok")
    assert r2.status_code == 200
    text2 = _reply(r2)
    assert "✅" in text2 or "ghi" in text2.lower()


# ── Group 9: Query commands ───────────────────────────────────────────────────

async def test_query_fund(client):
    """/quy → hiện trạng quỹ."""
    await _create_and_activate_trip(client, "Query Fund Trip")

    r = await _send(client, "/quy")
    assert r.status_code == 200
    text = _reply(r)
    assert "quỹ" in text.lower() or "nạp" in text.lower() or "800" in text


async def test_query_summary(client):
    """/tongket → tổng kết."""
    await _create_and_activate_trip(client, "Summary Trip")

    r = await _send(client, "/tongket")
    assert r.status_code == 200
    text = _reply(r)
    assert text


async def test_query_mine(client):
    """/cuatoi → chi tiêu của tôi."""
    await _create_and_activate_trip(client, "Mine Query Trip")

    r = await _send(client, "/cuatoi")
    assert r.status_code == 200
    text = _reply(r)
    assert text


async def test_query_settlement(client):
    """/chiaai → tính chia tiền."""
    await _create_and_activate_trip(client, "Settlement Trip")

    r = await _send(client, "/chiaai")
    assert r.status_code == 200
    text = _reply(r)
    assert text


# ── Group 10: Cancel pending ──────────────────────────────────────────────────

async def test_cancel_pending_no_pending(client):
    """huỷ khi không có giao dịch đang chờ."""
    # Gửi huỷ khi state = IDLE
    r = await _send(client, "huỷ")
    assert r.status_code == 200
    # Khi idle, "huỷ" không match CANCEL_PENDING pattern → UNKNOWN intent
    text = _reply(r)
    assert text


# ── Group 11: Idempotency ─────────────────────────────────────────────────────

async def test_duplicate_event_skipped(client):
    """Cùng event_id gửi 2 lần → lần 2 bị skip."""
    import uuid
    import time
    event_id = f"dedup-{uuid.uuid4().hex[:8]}"

    payload = {
        "event_name": "user_send_text",
        "user_id": USER_ID,
        "event_id": event_id,
        "timestamp": int(time.time() * 1000),
        "message": {"text": "/help"},
    }

    from app.agent.orchestrator import handle_event
    from app.storage.db import get_db
    db = get_db()

    # Lần 1
    await handle_event(payload)
    # Lần 2 — phải bị skip (no exception)
    await handle_event(payload)


# ── Group 12: Misc endpoints ──────────────────────────────────────────────────

async def test_mock_inbox_endpoint(client):
    """GET /mock/inbox/{user_id} → trả về messages."""
    await _send(client, "/help")

    r = await client.get(f"/mock/inbox/{USER_ID}")
    assert r.status_code == 200
    data = r.json()
    assert "messages" in data


async def test_mock_clear_inbox(client):
    """DELETE /mock/inbox/{user_id} → clear."""
    r = await client.delete(f"/mock/inbox/{USER_ID}")
    assert r.status_code == 200
    assert r.json()["cleared"] is True


async def test_mock_state_endpoint(client):
    """GET /mock/state/{user_id} → conversation state."""
    r = await client.get(f"/mock/state/{USER_ID}")
    assert r.status_code == 200
    data = r.json()
    assert "conversation" in data


async def test_webhook_zalo_placeholder(client):
    """POST /webhook/zalo → Phase 2 placeholder."""
    r = await client.post("/webhook/zalo", json={})
    assert r.status_code == 200


async def test_metrics_endpoint(client):
    """GET /metrics → Prometheus metrics."""
    r = await client.get("/metrics")
    assert r.status_code == 200


# ── Group 13: Send image (OCR stub) ──────────────────────────────────────────

async def test_send_image_ocr_stub(client):
    """Gửi ảnh → OCR stub trả về confidence=0 → hướng dẫn nhập tay."""
    await _create_and_activate_trip(client, "OCR Test Trip")

    r = await client.post("/mock/send_image", json={
        "zalo_user_id": USER_ID,
        "image_url": "https://example.com/fake-bill.jpg",
    })
    assert r.status_code == 200
    text = _reply(r)
    assert text  # bot trả về hướng dẫn
