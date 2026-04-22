"""Unit tests cho app/agent/trip_resolver.py."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.agent.trip_resolver import build_multi_trip_prompt, resolve_active_trip
from app.domain.models import Member, Trip, TripStatus
from app.storage.db import Database
from app.storage.repositories import ConversationRepository, MemberRepository, TripRepository
import app.storage.db as db_module


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    await database.init_schema()
    # Inject as singleton so resolve_active_trip can call get_db()
    original = db_module._db_instance
    db_module._db_instance = database
    yield database
    db_module._db_instance = original
    await database.close()


def _make_member(member_id="M001", name="Đức", zalo_id="zalo001") -> Member:
    return Member(
        id=member_id,
        zalo_user_id=zalo_id,
        display_name=name,
        is_admin=True,
        active=True,
        created_at=datetime.utcnow(),
    )


def _make_trip(trip_id="T001", name="Đà Lạt", status=TripStatus.ACTIVE, created_by="M001") -> Trip:
    return Trip(
        id=trip_id,
        name=name,
        start_date=datetime(2026, 5, 10),
        status=status,
        expected_member_count=2,
        initial_topup_per_member=800_000,
        created_by=created_by,
        created_at=datetime.utcnow(),
    )


# ── resolve_active_trip ───────────────────────────────────────────────────────

async def test_resolve_stored_trip_valid(db):
    """stored_trip_id hợp lệ → trả về trip đó."""
    member_repo = MemberRepository(db)
    trip_repo = TripRepository(db)

    member = _make_member()
    trip = _make_trip(status=TripStatus.ACTIVE)
    await member_repo.insert(member)
    await trip_repo.insert(trip)
    await trip_repo.add_member(trip.id, member.id)
    await db._conn.commit()

    result = await resolve_active_trip(
        member_id=member.id,
        zalo_user_id=member.zalo_user_id,
        stored_trip_id=trip.id,
    )
    assert result is not None
    assert result.id == trip.id


async def test_resolve_stored_trip_not_member(db):
    """stored_trip_id hợp lệ nhưng member không thuộc trip → None."""
    member_repo = MemberRepository(db)
    trip_repo = TripRepository(db)

    member = _make_member()
    trip = _make_trip(status=TripStatus.ACTIVE)
    other_member = _make_member(member_id="M999", name="Khách", zalo_id="zalo999")

    await member_repo.insert(member)
    await member_repo.insert(other_member)
    await trip_repo.insert(trip)
    await trip_repo.add_member(trip.id, other_member.id)  # member KHÔNG trong trip
    await db._conn.commit()

    result = await resolve_active_trip(
        member_id=member.id,
        zalo_user_id=member.zalo_user_id,
        stored_trip_id=trip.id,
    )
    assert result is None


async def test_resolve_stored_trip_wrong_status(db):
    """Trip có status SETTLED → không valid → fallback to search."""
    member_repo = MemberRepository(db)
    trip_repo = TripRepository(db)

    member = _make_member()
    trip = _make_trip(status=TripStatus.SETTLED)
    await member_repo.insert(member)
    await trip_repo.insert(trip)
    await trip_repo.add_member(trip.id, member.id)
    await db._conn.commit()

    result = await resolve_active_trip(
        member_id=member.id,
        zalo_user_id=member.zalo_user_id,
        stored_trip_id=trip.id,
    )
    assert result is None


async def test_resolve_no_stored_trip_one_active(db):
    """Không có stored_trip_id, member có 1 active trip → auto-select."""
    member_repo = MemberRepository(db)
    trip_repo = TripRepository(db)
    conv_repo = ConversationRepository(db)

    member = _make_member()
    trip = _make_trip(status=TripStatus.ACTIVE)
    await member_repo.insert(member)
    await trip_repo.insert(trip)
    await trip_repo.add_member(trip.id, member.id)
    await db._conn.commit()

    result = await resolve_active_trip(
        member_id=member.id,
        zalo_user_id=member.zalo_user_id,
        stored_trip_id=None,
    )
    assert result is not None
    assert result.id == trip.id

    # conv phải được cập nhật
    conv = await conv_repo.get(member.zalo_user_id)
    assert conv is not None
    assert conv["active_trip_id"] == trip.id


async def test_resolve_no_stored_trip_no_active(db):
    """Member không có trip active nào → None."""
    member_repo = MemberRepository(db)
    await member_repo.insert(_make_member())
    await db._conn.commit()

    result = await resolve_active_trip(
        member_id="M001",
        zalo_user_id="zalo001",
        stored_trip_id=None,
    )
    assert result is None


async def test_resolve_no_stored_trip_collecting_topup(db):
    """Trip COLLECTING_TOPUP → cũng được coi là candidate."""
    member_repo = MemberRepository(db)
    trip_repo = TripRepository(db)

    member = _make_member()
    trip = _make_trip(status=TripStatus.COLLECTING_TOPUP)
    await member_repo.insert(member)
    await trip_repo.insert(trip)
    await trip_repo.add_member(trip.id, member.id)
    await db._conn.commit()

    result = await resolve_active_trip(
        member_id=member.id,
        zalo_user_id=member.zalo_user_id,
        stored_trip_id=None,
    )
    assert result is not None
    assert result.id == trip.id


async def test_resolve_multiple_active_trips_returns_none(db):
    """Nhiều active trips → None (caller xử lý multi-trip prompt)."""
    member_repo = MemberRepository(db)
    trip_repo = TripRepository(db)

    member = _make_member()
    trip1 = _make_trip(trip_id="T001", name="Đà Lạt", status=TripStatus.ACTIVE)
    trip2 = _make_trip(trip_id="T002", name="Hội An", status=TripStatus.ACTIVE)

    await member_repo.insert(member)
    await trip_repo.insert(trip1)
    await trip_repo.insert(trip2)
    await trip_repo.add_member(trip1.id, member.id)
    await trip_repo.add_member(trip2.id, member.id)
    await db._conn.commit()

    result = await resolve_active_trip(
        member_id=member.id,
        zalo_user_id=member.zalo_user_id,
        stored_trip_id=None,
    )
    assert result is None


async def test_resolve_stored_trip_none_id(db):
    """stored_trip_id = None → fallback to search."""
    member_repo = MemberRepository(db)
    await member_repo.insert(_make_member())
    await db._conn.commit()

    result = await resolve_active_trip(
        member_id="M001",
        zalo_user_id="zalo001",
        stored_trip_id=None,
    )
    assert result is None  # no active trips


# ── build_multi_trip_prompt ───────────────────────────────────────────────────

def test_build_multi_trip_prompt_basic():
    trips = [
        _make_trip(trip_id="T001", name="Đà Lạt", status=TripStatus.ACTIVE),
        _make_trip(trip_id="T002", name="Hội An", status=TripStatus.ACTIVE),
    ]
    result = build_multi_trip_prompt(trips)

    assert "T001" in result
    assert "T002" in result
    assert "Đà Lạt" in result
    assert "Hội An" in result
    assert "/trip_switch" in result


def test_build_multi_trip_prompt_single():
    trips = [_make_trip(trip_id="T001", name="Phú Quốc")]
    result = build_multi_trip_prompt(trips)
    assert "T001" in result
    assert "/trip_switch" in result


def test_build_multi_trip_prompt_includes_status():
    trip = _make_trip(trip_id="T001", status=TripStatus.COLLECTING_TOPUP)
    result = build_multi_trip_prompt([trip])
    assert "collecting_topup" in result.lower()


def test_build_multi_trip_prompt_numbered():
    trips = [
        _make_trip(trip_id="T001", name="Trip A"),
        _make_trip(trip_id="T002", name="Trip B"),
        _make_trip(trip_id="T003", name="Trip C"),
    ]
    result = build_multi_trip_prompt(trips)
    assert "1." in result
    assert "2." in result
    assert "3." in result
