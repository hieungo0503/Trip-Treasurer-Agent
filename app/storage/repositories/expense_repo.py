"""Repository cho Expense + Contribution.

QUAN TRỌNG: mọi query PHẢI có WHERE trip_id để đảm bảo trip isolation.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from app.domain.models import (
    Contribution,
    ContributionKind,
    Expense,
    ExpenseCategory,
    ExpenseSource,
)
from app.storage.db import Database


def _row_to_expense(row: dict) -> Expense:
    return Expense(
        id=row["id"],
        trip_id=row["trip_id"],
        payer_id=row["payer_id"],
        amount_vnd=row["amount_vnd"],
        category=ExpenseCategory(row["category"]),
        description=row["description"],
        split_method=row["split_method"],
        split_member_ids=json.loads(row["split_member_ids"]),
        source=ExpenseSource(row["source"]),
        source_raw=row["source_raw"],
        ocr_confidence=row["ocr_confidence"],
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        confirmed_at=datetime.fromisoformat(row["confirmed_at"]),
        confirmed_by=row["confirmed_by"],
        source_event_id=row["source_event_id"],
        trace_id=row["trace_id"],
        status=row["status"],
    )


def _row_to_contribution(row: dict) -> Contribution:
    return Contribution(
        id=row["id"],
        trip_id=row["trip_id"],
        member_id=row["member_id"],
        amount_vnd=row["amount_vnd"],
        kind=ContributionKind(row["kind"]),
        linked_expense_id=row["linked_expense_id"],
        note=row["note"],
        occurred_at=datetime.fromisoformat(row["occurred_at"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        confirmed_at=datetime.fromisoformat(row["confirmed_at"]),
        source_event_id=row["source_event_id"],
        trace_id=row["trace_id"],
        status=row["status"],
    )


class ExpenseRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_by_id(self, trip_id: str, expense_id: str) -> Optional[Expense]:
        # trip_id bắt buộc — isolation guard
        row = await self._db.fetch_one(
            "SELECT * FROM expenses WHERE trip_id=? AND id=?",
            (trip_id, expense_id),
        )
        return _row_to_expense(row) if row else None

    async def list_active(self, trip_id: str) -> list[Expense]:
        rows = await self._db.fetch_all(
            "SELECT * FROM expenses WHERE trip_id=? AND status='active' ORDER BY created_at",
            (trip_id,),
        )
        return [_row_to_expense(r) for r in rows]

    async def insert(self, expense: Expense) -> None:
        await self._db.execute(
            """
            INSERT INTO expenses(
                id, trip_id, payer_id, amount_vnd, category, description,
                split_method, split_member_ids, source, source_raw, ocr_confidence,
                occurred_at, created_at, confirmed_at, confirmed_by,
                source_event_id, trace_id, status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                expense.id, expense.trip_id, expense.payer_id,
                expense.amount_vnd, expense.category.value, expense.description,
                expense.split_method, json.dumps(expense.split_member_ids),
                expense.source.value, expense.source_raw, expense.ocr_confidence,
                expense.occurred_at.isoformat(), expense.created_at.isoformat(),
                expense.confirmed_at.isoformat(), expense.confirmed_by,
                expense.source_event_id, expense.trace_id, expense.status,
            ),
        )

    async def cancel(self, trip_id: str, expense_id: str) -> None:
        await self._db.execute(
            "UPDATE expenses SET status='cancelled' WHERE trip_id=? AND id=?",
            (trip_id, expense_id),
        )


class ContributionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_by_id(self, trip_id: str, contrib_id: str) -> Optional[Contribution]:
        row = await self._db.fetch_one(
            "SELECT * FROM contributions WHERE trip_id=? AND id=?",
            (trip_id, contrib_id),
        )
        return _row_to_contribution(row) if row else None

    async def list_active(self, trip_id: str) -> list[Contribution]:
        rows = await self._db.fetch_all(
            "SELECT * FROM contributions WHERE trip_id=? AND status='active' ORDER BY created_at",
            (trip_id,),
        )
        return [_row_to_contribution(r) for r in rows]

    async def list_by_member(self, trip_id: str, member_id: str) -> list[Contribution]:
        rows = await self._db.fetch_all(
            """
            SELECT * FROM contributions
            WHERE trip_id=? AND member_id=? AND status='active'
            ORDER BY created_at
            """,
            (trip_id, member_id),
        )
        return [_row_to_contribution(r) for r in rows]

    async def insert(self, contrib: Contribution) -> None:
        await self._db.execute(
            """
            INSERT INTO contributions(
                id, trip_id, member_id, amount_vnd, kind, linked_expense_id,
                note, occurred_at, created_at, confirmed_at,
                source_event_id, trace_id, status)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                contrib.id, contrib.trip_id, contrib.member_id,
                contrib.amount_vnd, contrib.kind.value, contrib.linked_expense_id,
                contrib.note,
                contrib.occurred_at.isoformat(), contrib.created_at.isoformat(),
                contrib.confirmed_at.isoformat(),
                contrib.source_event_id, contrib.trace_id, contrib.status,
            ),
        )

    async def cancel(self, trip_id: str, contrib_id: str) -> None:
        await self._db.execute(
            "UPDATE contributions SET status='cancelled' WHERE trip_id=? AND id=?",
            (trip_id, contrib_id),
        )
