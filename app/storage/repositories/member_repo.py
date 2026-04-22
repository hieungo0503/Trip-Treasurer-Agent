"""Repository cho Member — global, cross-trip."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.domain.models import Member
from app.storage.db import Database


def _row_to_member(row: dict) -> Member:
    return Member(
        id=row["id"],
        zalo_user_id=row["zalo_user_id"],
        display_name=row["display_name"],
        full_name=row["full_name"],
        is_admin=bool(row["is_admin"]),
        active=bool(row["active"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class MemberRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_by_id(self, member_id: str) -> Optional[Member]:
        row = await self._db.fetch_one(
            "SELECT * FROM members WHERE id = ?", (member_id,)
        )
        return _row_to_member(row) if row else None

    async def get_by_zalo_user_id(self, zalo_user_id: str) -> Optional[Member]:
        row = await self._db.fetch_one(
            "SELECT * FROM members WHERE zalo_user_id = ? AND active = 1",
            (zalo_user_id,),
        )
        return _row_to_member(row) if row else None

    async def get_by_display_name(self, display_name: str, active: bool = True) -> list[Member]:
        """Exact match trên display_name. Fuzzy match do domain layer xử lý."""
        rows = await self._db.fetch_all(
            "SELECT * FROM members WHERE display_name = ? AND active = ?",
            (display_name, int(active)),
        )
        return [_row_to_member(r) for r in rows]

    async def get_all_active(self) -> list[Member]:
        rows = await self._db.fetch_all(
            "SELECT * FROM members WHERE active = 1 ORDER BY display_name"
        )
        return [_row_to_member(r) for r in rows]

    async def insert(self, member: Member) -> None:
        await self._db.execute(
            """
            INSERT INTO members(id, zalo_user_id, display_name, full_name,
                                is_admin, active, created_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                member.id,
                member.zalo_user_id,
                member.display_name,
                member.full_name,
                int(member.is_admin),
                int(member.active),
                member.created_at.isoformat(),
            ),
        )

    async def link_zalo(self, member_id: str, zalo_user_id: str) -> None:
        """Link zalo_user_id vào placeholder member."""
        await self._db.execute(
            "UPDATE members SET zalo_user_id = ? WHERE id = ?",
            (zalo_user_id, member_id),
        )

    async def deactivate(self, member_id: str) -> None:
        await self._db.execute(
            "UPDATE members SET active = 0 WHERE id = ?", (member_id,)
        )
