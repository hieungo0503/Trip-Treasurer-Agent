"""Tests cho storage layer — DB + repositories (in-memory SQLite)."""

import pytest
from datetime import datetime, timedelta

from app.storage.db import Database
from app.storage.repositories import (
    MemberRepository,
    TripRepository,
    ExpenseRepository,
    ContributionRepository,
    ConversationRepository,
    PendingRepository,
    SheetOutboxRepository,
    AuditLogRepository,
)
from app.domain.models import (
    Member,
    Trip,
    TripStatus,
    Expense,
    ExpenseCategory,
    ExpenseSource,
    Contribution,
    ContributionKind,
)


@pytest.fixture
async def db():
    """In-memory SQLite cho mỗi test."""
    database = Database(":memory:")
    await database.connect()
    await database.init_schema()
    yield database
    await database.close()


def _make_member(member_id: str = "M001", name: str = "Đức", is_admin: bool = True) -> Member:
    return Member(
        id=member_id,
        display_name=name,
        is_admin=is_admin,
        active=True,
        created_at=datetime.utcnow(),
    )


def _make_trip(trip_id: str = "TRIP-001", created_by: str = "M001") -> Trip:
    return Trip(
        id=trip_id,
        name="Đà Lạt",
        start_date=datetime(2026, 5, 10),
        status=TripStatus.ACTIVE,
        expected_member_count=3,
        initial_topup_per_member=800_000,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )


def _make_expense(trip_id: str = "TRIP-001", payer_id: str = "M001") -> Expense:
    return Expense(
        id="E001",
        trip_id=trip_id,
        payer_id=payer_id,
        amount_vnd=500_000,
        category=ExpenseCategory.FOOD,
        description="Ăn tối",
        split_member_ids=["M001", "M002", "M003"],
        source=ExpenseSource.TEXT,
        occurred_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        confirmed_at=datetime.utcnow(),
        confirmed_by=payer_id,
    )


def _make_contribution(trip_id: str = "TRIP-001", member_id: str = "M001") -> Contribution:
    return Contribution(
        id="C001",
        trip_id=trip_id,
        member_id=member_id,
        amount_vnd=800_000,
        kind=ContributionKind.INITIAL_TOPUP,
        occurred_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        confirmed_at=datetime.utcnow(),
    )


# ── DB core ──────────────────────────────────────────────────────────────────

class TestDatabase:
    async def test_fetch_one_not_found(self, db):
        result = await db.fetch_one("SELECT * FROM members WHERE id='NOTEXIST'")
        assert result is None

    async def test_fetch_all_empty(self, db):
        result = await db.fetch_all("SELECT * FROM members")
        assert result == []

    async def test_settings(self, db):
        await db.set_setting("bot_enabled", "true")
        val = await db.get_setting("bot_enabled")
        assert val == "true"

    async def test_settings_default(self, db):
        val = await db.get_setting("nonexistent", default="fallback")
        assert val == "fallback"

    async def test_idempotency(self, db):
        assert not await db.is_event_processed("EVT-001")
        await db.mark_event_processed("EVT-001")
        await db._conn.commit()
        assert await db.is_event_processed("EVT-001")

    async def test_idempotency_duplicate_insert_ignored(self, db):
        await db.mark_event_processed("EVT-DUP")
        await db.mark_event_processed("EVT-DUP")  # không raise
        await db._conn.commit()


# ── Member repo ───────────────────────────────────────────────────────────────

class TestMemberRepository:
    async def test_insert_and_get_by_id(self, db):
        repo = MemberRepository(db)
        member = _make_member()
        await repo.insert(member)
        await db._conn.commit()

        found = await repo.get_by_id("M001")
        assert found is not None
        assert found.display_name == "Đức"
        assert found.is_admin is True

    async def test_get_by_zalo_user_id(self, db):
        repo = MemberRepository(db)
        member = _make_member()
        await repo.insert(member)
        await db.execute("UPDATE members SET zalo_user_id='ZL001' WHERE id='M001'")
        await db._conn.commit()

        found = await repo.get_by_zalo_user_id("ZL001")
        assert found is not None
        assert found.id == "M001"

    async def test_get_by_display_name(self, db):
        repo = MemberRepository(db)
        await repo.insert(_make_member("M001", "Hà"))
        await repo.insert(_make_member("M002", "Hà"))
        await repo.insert(_make_member("M003", "Long"))
        await db._conn.commit()

        results = await repo.get_by_display_name("Hà")
        assert len(results) == 2

    async def test_get_all_active(self, db):
        repo = MemberRepository(db)
        await repo.insert(_make_member("M001", "Đức"))
        await repo.insert(_make_member("M002", "Hà"))
        await db._conn.commit()

        results = await repo.get_all_active()
        assert len(results) == 2

    async def test_not_found_returns_none(self, db):
        repo = MemberRepository(db)
        assert await repo.get_by_id("NOTEXIST") is None


# ── Trip repo ─────────────────────────────────────────────────────────────────

class TestTripRepository:
    async def test_insert_and_get(self, db):
        member_repo = MemberRepository(db)
        await member_repo.insert(_make_member())
        await db._conn.commit()

        trip_repo = TripRepository(db)
        trip = _make_trip()
        await trip_repo.insert(trip)
        await db._conn.commit()

        found = await trip_repo.get_by_id("TRIP-001")
        assert found is not None
        assert found.name == "Đà Lạt"
        assert found.status == TripStatus.ACTIVE

    async def test_update_status(self, db):
        member_repo = MemberRepository(db)
        await member_repo.insert(_make_member())
        await db._conn.commit()

        trip_repo = TripRepository(db)
        await trip_repo.insert(_make_trip())
        await trip_repo.update_status("TRIP-001", TripStatus.SETTLED)
        await db._conn.commit()

        found = await trip_repo.get_by_id("TRIP-001")
        assert found.status == TripStatus.SETTLED

    async def test_add_and_check_member(self, db):
        member_repo = MemberRepository(db)
        await member_repo.insert(_make_member("M001"))
        await member_repo.insert(_make_member("M002", "Hà"))
        await db._conn.commit()

        trip_repo = TripRepository(db)
        await trip_repo.insert(_make_trip())
        await trip_repo.add_member("TRIP-001", "M001")
        await trip_repo.add_member("TRIP-001", "M002")
        await db._conn.commit()

        assert await trip_repo.is_member("TRIP-001", "M001")
        assert await trip_repo.is_member("TRIP-001", "M002")
        assert not await trip_repo.is_member("TRIP-001", "M003")

    async def test_get_active_trips_for_member(self, db):
        member_repo = MemberRepository(db)
        await member_repo.insert(_make_member("M001"))
        await db._conn.commit()

        trip_repo = TripRepository(db)
        await trip_repo.insert(_make_trip("TRIP-001"))
        await trip_repo.add_member("TRIP-001", "M001")
        await db._conn.commit()

        trips = await trip_repo.get_active_trips_for_member("M001")
        assert len(trips) == 1
        assert trips[0].id == "TRIP-001"

    async def test_get_member_ids(self, db):
        member_repo = MemberRepository(db)
        await member_repo.insert(_make_member("M001"))
        await member_repo.insert(_make_member("M002", "Hà"))
        await db._conn.commit()

        trip_repo = TripRepository(db)
        await trip_repo.insert(_make_trip())
        await trip_repo.add_member("TRIP-001", "M001")
        await trip_repo.add_member("TRIP-001", "M002")
        await db._conn.commit()

        ids = await trip_repo.get_member_ids("TRIP-001")
        assert set(ids) == {"M001", "M002"}


# ── Expense / Contribution repo ───────────────────────────────────────────────

class TestExpenseRepository:
    async def _setup(self, db):
        member_repo = MemberRepository(db)
        await member_repo.insert(_make_member("M001"))
        trip_repo = TripRepository(db)
        await trip_repo.insert(_make_trip())
        await db._conn.commit()

    async def test_insert_and_list_active(self, db):
        await self._setup(db)
        repo = ExpenseRepository(db)
        expense = _make_expense()
        await repo.insert(expense)
        await db._conn.commit()

        results = await repo.list_active("TRIP-001")
        assert len(results) == 1
        assert results[0].amount_vnd == 500_000
        assert results[0].category == ExpenseCategory.FOOD

    async def test_cancel_expense(self, db):
        await self._setup(db)
        repo = ExpenseRepository(db)
        await repo.insert(_make_expense())
        await db._conn.commit()

        await repo.cancel("TRIP-001", "E001")
        await db._conn.commit()

        results = await repo.list_active("TRIP-001")
        assert len(results) == 0

    async def test_trip_isolation_enforced(self, db):
        await self._setup(db)
        repo = ExpenseRepository(db)
        await repo.insert(_make_expense("TRIP-001"))
        await db._conn.commit()

        # Query với trip_id khác → không thấy
        results = await repo.list_active("TRIP-999")
        assert len(results) == 0


class TestContributionRepository:
    async def _setup(self, db):
        await MemberRepository(db).insert(_make_member("M001"))
        await TripRepository(db).insert(_make_trip())
        await db._conn.commit()

    async def test_insert_and_list_active(self, db):
        await self._setup(db)
        repo = ContributionRepository(db)
        contrib = _make_contribution()
        await repo.insert(contrib)
        await db._conn.commit()

        results = await repo.list_active("TRIP-001")
        assert len(results) == 1
        assert results[0].kind == ContributionKind.INITIAL_TOPUP

    async def test_list_by_member(self, db):
        await self._setup(db)
        repo = ContributionRepository(db)
        await repo.insert(_make_contribution("TRIP-001", "M001"))
        await db._conn.commit()

        results = await repo.list_by_member("TRIP-001", "M001")
        assert len(results) == 1

        empty = await repo.list_by_member("TRIP-001", "M002")
        assert len(empty) == 0


# ── Conversation + Pending repo ───────────────────────────────────────────────

class TestConversationRepository:
    async def test_upsert_and_get(self, db):
        repo = ConversationRepository(db)
        await repo.upsert("ZL001", state="idle")
        await db._conn.commit()

        conv = await repo.get("ZL001")
        assert conv is not None
        assert conv["state"] == "idle"

    async def test_set_state(self, db):
        repo = ConversationRepository(db)
        await repo.upsert("ZL001", state="idle")
        await repo.set_state("ZL001", "awaiting_confirm", None)
        await db._conn.commit()

        conv = await repo.get("ZL001")
        assert conv["state"] == "awaiting_confirm"
        assert conv["pending_id"] is None

    async def test_get_nonexistent_returns_none(self, db):
        repo = ConversationRepository(db)
        assert await repo.get("NOTEXIST") is None


class TestPendingRepository:
    async def _setup_member_trip(self, db):
        await MemberRepository(db).insert(_make_member())
        await TripRepository(db).insert(_make_trip())
        await db._conn.commit()

    async def test_insert_and_get(self, db):
        await self._setup_member_trip(db)
        repo = PendingRepository(db)
        expires = datetime.utcnow() + timedelta(minutes=30)
        pending_id = await repo.insert(
            zalo_user_id="ZL001",
            kind="expense",
            payload={"amount": 500000},
            expires_at=expires,
            trip_id="TRIP-001",
        )
        await db._conn.commit()

        found = await repo.get(pending_id)
        assert found is not None
        assert found["kind"] == "expense"
        assert found["state"] == "awaiting_confirm"

    async def test_confirm_changes_state(self, db):
        await self._setup_member_trip(db)
        repo = PendingRepository(db)
        expires = datetime.utcnow() + timedelta(minutes=30)
        pending_id = await repo.insert("ZL001", "expense", {}, expires, "TRIP-001")
        await repo.confirm(pending_id)
        await db._conn.commit()

        found = await repo.get(pending_id)
        assert found["state"] == "confirmed"

    async def test_cancel_changes_state(self, db):
        await self._setup_member_trip(db)
        repo = PendingRepository(db)
        expires = datetime.utcnow() + timedelta(minutes=30)
        pending_id = await repo.insert("ZL001", "expense", {}, expires, "TRIP-001")
        await repo.cancel(pending_id)
        await db._conn.commit()

        found = await repo.get(pending_id)
        assert found["state"] == "cancelled"


# ── AuditLog + SheetOutbox ────────────────────────────────────────────────────

class TestAuditLogRepository:
    async def test_insert_audit_log(self, db):
        await MemberRepository(db).insert(_make_member())
        await TripRepository(db).insert(_make_trip())
        await db._conn.commit()

        repo = AuditLogRepository(db)
        await repo.insert(
            action="expense.committed",
            trip_id="TRIP-001",
            actor_id="M001",
            entity_id="E001",
            details={"amount": 500000},
            trace_id="TRACE-001",
        )
        await db._conn.commit()

        rows = await db.fetch_all("SELECT * FROM audit_log WHERE trip_id='TRIP-001'")
        assert len(rows) == 1
        assert rows[0]["action"] == "expense.committed"


class TestSheetOutboxRepository:
    async def _setup(self, db):
        await MemberRepository(db).insert(_make_member())
        await TripRepository(db).insert(_make_trip())
        await db._conn.commit()

    async def test_insert_and_list_pending(self, db):
        await self._setup(db)
        repo = SheetOutboxRepository(db)
        await repo.insert("TRIP-001", "append_expense", {"expense_id": "E001"})
        await db._conn.commit()

        pending = await repo.list_pending()
        assert len(pending) == 1
        assert pending[0]["op"] == "append_expense"

    async def test_mark_done(self, db):
        await self._setup(db)
        repo = SheetOutboxRepository(db)
        outbox_id = await repo.insert("TRIP-001", "append_expense", {})
        await repo.mark_done(outbox_id)
        await db._conn.commit()

        pending = await repo.list_pending()
        assert len(pending) == 0
