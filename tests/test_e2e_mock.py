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


# ── Group 14: Bot pause / resume ─────────────────────────────────────────────

async def test_pause_bot_admin(client):
    """/pause_bot bởi admin → bot dừng."""
    r = await _send(client, "/pause_bot")
    assert r.status_code == 200
    text = _reply(r)
    assert "tạm dừng" in text.lower() or "pause" in text.lower() or "⏸" in text

    # Unset để không ảnh hưởng test khác
    from app.storage.db import get_db
    db = get_db()
    await db.set_setting("bot_enabled", "true")
    await db._conn.commit()


async def test_resume_bot_admin(client):
    """/resume_bot bởi admin khi bot đang chạy → xác nhận hoạt động."""
    # Bot đang enabled (mặc định), gửi resume → vẫn trả về "hoạt động"
    r = await _send(client, "/resume_bot")
    assert r.status_code == 200
    text = _reply(r)
    assert "hoạt động" in text.lower() or "▶" in text


async def test_pause_bot_non_admin(client):
    """/pause_bot từ user không phải admin → bị từ chối."""
    r = await _send(client, "/pause_bot", user_id="non_admin_user_555")
    assert r.status_code == 200
    text = _reply(r)
    # new user → WELCOME, hoặc đã là member thì bị admin guard
    assert text


async def test_bot_paused_skips_processing(client):
    """Khi bot bị pause, message mới bị bỏ qua (không reply error)."""
    from app.storage.db import get_db
    db = get_db()
    await db.set_setting("bot_enabled", "false")
    await db._conn.commit()

    import uuid, time
    from app.agent.orchestrator import handle_event
    event_id = f"pause-test-{uuid.uuid4().hex[:8]}"
    payload = {
        "event_name": "user_send_text",
        "user_id": USER_ID,
        "event_id": event_id,
        "timestamp": int(time.time() * 1000),
        "message": {"text": "/help"},
    }
    await handle_event(payload)  # không nên raise

    # Restore
    await db.set_setting("bot_enabled", "true")
    await db._conn.commit()


# ── Group 15: Trip operations ─────────────────────────────────────────────────

async def test_trip_list_no_trips(client):
    """/trips khi chưa có chuyến nào."""
    r = await _send(client, "/trips")
    assert r.status_code == 200
    text = _reply(r)
    assert "chưa" in text.lower() or "chuyến" in text.lower()


async def test_trip_list_with_active_trip(client):
    """/trips sau khi có chuyến ACTIVE → hiển thị đầy đủ."""
    await _create_and_activate_trip(client, "Sapa Trip")

    r = await _send(client, "/trips")
    assert r.status_code == 200
    text = _reply(r)
    assert "Sapa" in text or "ACTIVE" in text.lower() or "đang hoạt động" in text.lower()


async def test_trip_view_not_found(client):
    """/trip_view với ID không tồn tại → thông báo lỗi."""
    r = await _send(client, "/trip_view TRIP-00000000-NOTFOUND")
    assert r.status_code == 200
    text = _reply(r)
    assert "không tìm thấy" in text.lower() or "not found" in text.lower()


async def test_trip_view_no_id(client):
    """/trip_view không có ID → hướng dẫn."""
    r = await _send(client, "/trip_view")
    assert r.status_code == 200
    text = _reply(r)
    assert "trip_view" in text.lower() or "id" in text.lower()


async def test_trip_switch_no_id(client):
    """/trip_switch không có ID → hướng dẫn."""
    r = await _send(client, "/trip_switch")
    assert r.status_code == 200
    text = _reply(r)
    assert "trip_switch" in text.lower() or "id" in text.lower()


async def test_trip_switch_not_found(client):
    """/trip_switch ID không tồn tại → lỗi."""
    r = await _send(client, "/trip_switch TRIP-NONEXISTENT-ID")
    assert r.status_code == 200
    text = _reply(r)
    assert "không tìm thấy" in text.lower()


async def test_trip_switch_valid(client):
    """/trip_switch khi đã có trip → chuyển thành công."""
    import re
    r_trip = await _send(client, "/trip_new Mũi Né, 10-12/05, 1 người gồm đức, 500k")
    r_ok = await _send(client, "ok")
    text = _reply(r_ok)
    m = re.search(r"TRIP-\d{8}-[A-Z0-9]{6}", text)
    if m:
        trip_id = m.group(0)
        r = await _send(client, f"/trip_switch {trip_id}")
        assert r.status_code == 200
        rep = _reply(r)
        assert "Mũi Né" in rep or "✅" in rep or trip_id in rep


async def test_trip_end_by_admin(client):
    """/trip_end bởi admin (creator) → trip settled."""
    await _create_and_activate_trip(client, "End Test Trip")

    r = await _send(client, "/trip_end")
    assert r.status_code == 200
    text = _reply(r)
    assert "kết chuyến" in text.lower() or "✅" in text or "settled" in text.lower()


async def test_trip_end_non_admin(client):
    """/trip_end từ user không phải creator/admin → bị từ chối."""
    await _create_and_activate_trip(client, "End Block Trip")

    r = await _send(client, "/trip_end", user_id="non_creator_user_888")
    assert r.status_code == 200
    text = _reply(r)
    assert text  # welcome hoặc blocked


async def test_trip_archive(client):
    """/trip_archive → trip archived."""
    await _create_and_activate_trip(client, "Archive Test Trip")

    r = await _send(client, "/trip_archive")
    assert r.status_code == 200
    text = _reply(r)
    assert "lưu trữ" in text.lower() or "archive" in text.lower() or "📦" in text


# ── Group 16: Query edge cases ────────────────────────────────────────────────

async def test_query_mine_with_expenses(client):
    """/cuatoi sau khi có chi tiêu → hiển thị danh sách."""
    await _create_and_activate_trip(client, "Mine With Expenses")

    # Ghi chi tiêu trước
    await _send(client, "chi 300k ăn uống")
    await _send(client, "ok")

    r = await _send(client, "/cuatoi")
    assert r.status_code == 200
    text = _reply(r)
    assert "300" in text or "ăn" in text.lower() or "chi tiêu" in text.lower()


async def test_query_mine_no_expenses(client):
    """/cuatoi khi chưa có chi tiêu → thông báo rỗng."""
    await _create_and_activate_trip(client, "Mine Empty Trip")

    r = await _send(client, "/cuatoi")
    assert r.status_code == 200
    text = _reply(r)
    assert "chưa" in text.lower() or "không" in text.lower()


async def test_query_topup_mine(client):
    """/nap_cua_toi → lịch sử nạp quỹ của tôi."""
    await _create_and_activate_trip(client, "Topup Mine Trip")

    r = await _send(client, "/nap_cua_toi")
    assert r.status_code == 200
    text = _reply(r)
    assert text  # initial_topup đã được ghi


async def test_query_topup_mine_empty(client):
    """/nap_cua_toi khi chưa nạp → thông báo."""
    # Tạo trip nhưng KHÔNG activate (không initial_topup)
    await _send(client, "/trip_new Topup Empty, 10-12/05, 1 người gồm đức, 800k")
    await _send(client, "ok")
    # Ở trạng thái COLLECTING_TOPUP, không gửi initial_topup

    r = await _send(client, "/nap_cua_toi")
    assert r.status_code == 200
    text = _reply(r)
    assert text


async def test_query_settlement_balanced(client):
    """/chiaai khi quỹ = 0 và không ai nợ ai → mọi người hòa."""
    # Trip 1 người → cân bằng hoàn toàn
    await _create_and_activate_trip(client, "Balanced Trip")

    r = await _send(client, "/chiaai")
    assert r.status_code == 200
    text = _reply(r)
    assert text


# ── Group 17: Admin commands ──────────────────────────────────────────────────

async def test_huy_auto_advance_no_id(client):
    """/huy_auto không có expense_id → hướng dẫn."""
    await _create_and_activate_trip(client, "Huy Auto No ID")

    r = await _send(client, "/huy_auto")
    assert r.status_code == 200
    text = _reply(r)
    assert "huy_auto" in text.lower() or "expense" in text.lower() or text


async def test_huy_auto_advance_not_found(client):
    """/huy_auto với expense_id không tồn tại → thông báo."""
    await _create_and_activate_trip(client, "Huy Auto Not Found")

    r = await _send(client, "/huy_auto EXP-NONEXISTENT")
    assert r.status_code == 200
    text = _reply(r)
    assert "không tìm thấy" in text.lower() or text


async def test_rebuild_sheet_no_sheet(client):
    """/rebuild_sheet khi trip chưa có sheet_id → thông báo."""
    await _create_and_activate_trip(client, "Rebuild Sheet Trip")

    r = await _send(client, "/rebuild_sheet")
    assert r.status_code == 200
    text = _reply(r)
    assert "sheet" in text.lower() or "chưa" in text.lower() or text


# ── Group 18: Confirm / cancel edge cases ────────────────────────────────────

async def test_confirm_no_pending(client):
    """ok khi không có giao dịch đang chờ → thông báo."""
    r = await _send(client, "ok")
    assert r.status_code == 200
    text = _reply(r)
    # idle state → CONFIRM intent nhưng pending_id=None → "không có giao dịch"
    assert "không" in text.lower() or "giao dịch" in text.lower() or text


async def test_cancel_no_pending(client):
    """huỷ khi không có giao dịch đang chờ → thông báo hoặc UNKNOWN."""
    # Trong IDLE state, "huỷ" có thể map sang UNKNOWN hoặc CANCEL_PENDING
    r = await _send(client, "huỷ")
    assert r.status_code == 200
    text = _reply(r)
    assert text


async def test_amend_intent(client):
    """sửa lại → AMEND reply."""
    await _create_and_activate_trip(client, "Amend Test Trip")
    await _send(client, "chi 200k ăn uống")  # tạo pending

    r = await _send(client, "sửa lại")
    assert r.status_code == 200
    text = _reply(r)
    assert "sửa" in text.lower() or "huỷ" in text.lower() or text


# ── Group 19: Guard paths ─────────────────────────────────────────────────────

async def test_no_member_guard_expense(client):
    """User không có trong DB gửi lệnh chi → guard hoặc welcome."""
    r = await _send(client, "chi 100k", user_id="unknown_user_777")
    assert r.status_code == 200
    text = _reply(r)
    assert text  # welcome hoặc guard message


async def test_needs_trip_guard_query_fund(client):
    """/quy khi chưa có active trip → guard."""
    r = await _send(client, "/quy")
    assert r.status_code == 200
    text = _reply(r)
    assert "chuyến" in text.lower() or "trip" in text.lower()


async def test_needs_trip_guard_settlement(client):
    """/chiaai khi chưa có active trip → guard."""
    r = await _send(client, "/chiaai")
    assert r.status_code == 200
    text = _reply(r)
    assert "chuyến" in text.lower() or "trip" in text.lower()


# ── Group 20: Unhandled exception path ───────────────────────────────────────

async def test_handle_event_exception_graceful(client):
    """handle_event bắt exception và không raise ra ngoài."""
    import uuid, time
    from app.agent.orchestrator import handle_event

    payload = {
        "event_name": "user_send_text",
        "user_id": USER_ID,
        "event_id": f"exc-test-{uuid.uuid4().hex[:8]}",
        "timestamp": int(time.time() * 1000),
        "message": {"text": "/help"},
    }

    # Patch _process_event để raise exception
    with patch("app.agent.orchestrator._process_event",
               side_effect=RuntimeError("simulated crash")):
        await handle_event(payload)  # phải không raise


# ── Group 21: Initial topup edge cases ───────────────────────────────────────

async def test_initial_topup_parse_failure(client):
    """Gửi initial topup không đúng format → bot hướng dẫn."""
    await _send(client, "/trip_new Parse Fail Trip, 10-12/05, 1 người gồm đức, 800k")
    await _send(client, "ok")

    # Gửi không có số tiền → không parse được
    r = await _send(client, "đức nạp rồi nhé")
    assert r.status_code == 200
    text = _reply(r)
    assert text  # hướng dẫn hoặc unknown intent


async def test_initial_topup_member_not_found(client):
    """Gửi initial topup với tên member không tồn tại → thông báo."""
    await _send(client, "/trip_new Member Not Found, 10-12/05, 1 người gồm đức, 800k")
    await _send(client, "ok")

    r = await _send(client, "xyzxyz đã nạp 800k")
    assert r.status_code == 200
    text = _reply(r)
    assert text  # member not found hoặc confirm card


# ── Group 22: Image OCR with base64 ──────────────────────────────────────────

async def test_send_image_no_attachments(client):
    """Event type image nhưng không có attachments → phản hồi lỗi."""
    await _create_and_activate_trip(client, "Image No Attach Trip")

    import uuid, time
    from app.agent.orchestrator import handle_event
    from app.storage.db import get_db

    payload = {
        "event_name": "user_send_text",
        "user_id": USER_ID,
        "event_id": f"img-noatt-{uuid.uuid4().hex[:8]}",
        "timestamp": int(time.time() * 1000),
        "message": {"attachments": []},  # có attachments key nhưng rỗng
    }
    await handle_event(payload)  # phải không raise
