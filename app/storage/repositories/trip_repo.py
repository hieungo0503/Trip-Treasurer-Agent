"""Repository cho Trip + TripMember."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.domain.models import Trip, TripStatus
from app.storage.db import Database


def _row_to_trip(row: dict) -> Trip:
    def _dt(v: str | None) -> Optional[datetime]:
        return datetime.fromisoformat(v) if v else None

    return Trip(
        id=row["id"],
        name=row["name"],
        start_date=datetime.fromisoformat(row["start_date"]),
        end_date=_dt(row["end_date"]),
        status=TripStatus(row["status"]),
        expected_member_count=row["expected_member_count"],
        initial_topup_per_member=row["initial_topup_per_member"],
        sheet_id=row["sheet_id"],
        sheet_url=row["sheet_url"],
        created_by=row["created_by"],
        created_at=datetime.fromisoformat(row["created_at"]),
        settled_at=_dt(row["settled_at"]),
        archived_at=_dt(row["archived_at"]),
    )


class TripRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_by_id(self, trip_id: str) -> Optional[Trip]:
        row = await self._db.fetch_one(
            "SELECT * FROM trips WHERE id = ?", (trip_id,)
        )
        return _row_to_trip(row) if row else None

    async def get_active_trips_for_member(self, member_id: str) -> list[Trip]:
        """Trip ACTIVE mà member tham gia — dùng cho resolve_trip_context."""
        rows = await self._db.fetch_all(
            """
            SELECT t.* FROM trips t
            JOIN trip_members tm ON tm.trip_id = t.id
            WHERE tm.member_id = ?
              AND tm.left_at IS NULL
              AND t.status = 'active'
            ORDER BY t.created_at DESC
            """,
            (member_id,),
        )
        return [_row_to_trip(r) for r in rows]

    async def get_all_trips_for_member(self, member_id: str) -> list[Trip]:
        rows = await self._db.fetch_all(
            """
            SELECT t.* FROM trips t
            JOIN trip_members tm ON tm.trip_id = t.id
            WHERE tm.member_id = ?
              AND tm.left_at IS NULL
            ORDER BY t.created_at DESC
            """,
            (member_id,),
        )
        return [_row_to_trip(r) for r in rows]

    async def insert(self, trip: Trip) -> None:
        def _s(v: datetime | None) -> Optional[str]:
            return v.isoformat() if v else None

        await self._db.execute(
            """
            INSERT INTO trips(id, name, start_date, end_date, status,
                expected_member_count, initial_topup_per_member,
                sheet_id, sheet_url, created_by, created_at,
                settled_at, archived_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                trip.id, trip.name,
                trip.start_date.isoformat(), _s(trip.end_date),
                trip.status.value, trip.expected_member_count,
                trip.initial_topup_per_member,
                trip.sheet_id, trip.sheet_url, trip.created_by,
                trip.created_at.isoformat(),
                _s(trip.settled_at), _s(trip.archived_at),
            ),
        )

    async def update_status(self, trip_id: str, status: TripStatus) -> None:
        await self._db.execute(
            "UPDATE trips SET status = ? WHERE id = ?",
            (status.value, trip_id),
        )

    async def update_sheet(self, trip_id: str, sheet_id: str, sheet_url: str) -> None:
        await self._db.execute(
            "UPDATE trips SET sheet_id = ?, sheet_url = ? WHERE id = ?",
            (sheet_id, sheet_url, trip_id),
        )

    async def set_settled(self, trip_id: str, settled_at: datetime) -> None:
        await self._db.execute(
            "UPDATE trips SET status='settled', settled_at=? WHERE id=?",
            (settled_at.isoformat(), trip_id),
        )

    async def set_archived(self, trip_id: str, archived_at: datetime) -> None:
        await self._db.execute(
            "UPDATE trips SET status='archived', archived_at=? WHERE id=?",
            (archived_at.isoformat(), trip_id),
        )

    # ── TripMember ────────────────────────────────────────────────────────

    async def add_member(self, trip_id: str, member_id: str) -> None:
        await self._db.execute(
            """
            INSERT OR IGNORE INTO trip_members(trip_id, member_id, joined_at)
            VALUES(?,?,?)
            """,
            (trip_id, member_id, datetime.utcnow().isoformat()),
        )

    async def remove_member(self, trip_id: str, member_id: str) -> None:
        await self._db.execute(
            "UPDATE trip_members SET left_at=? WHERE trip_id=? AND member_id=?",
            (datetime.utcnow().isoformat(), trip_id, member_id),
        )

    async def get_member_ids(self, trip_id: str) -> list[str]:
        rows = await self._db.fetch_all(
            "SELECT member_id FROM trip_members WHERE trip_id=? AND left_at IS NULL",
            (trip_id,),
        )
        return [r["member_id"] for r in rows]

    async def is_member(self, trip_id: str, member_id: str) -> bool:
        row = await self._db.fetch_one(
            "SELECT 1 FROM trip_members WHERE trip_id=? AND member_id=? AND left_at IS NULL",
            (trip_id, member_id),
        )
        return row is not None
