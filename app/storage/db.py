"""
Database layer — async SQLite via aiosqlite.

Conventions:
- Mọi method trả về dict hoặc dataclass, không trả raw Row.
- Mọi query trên expenses/contributions PHẢI có trip_id — enforce ở đây.
- Transaction context manager: async with db.transaction()
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator

import aiosqlite
import structlog

log = structlog.get_logger()

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS members (
    id            TEXT PRIMARY KEY,
    zalo_user_id  TEXT UNIQUE,
    display_name  TEXT NOT NULL,
    full_name     TEXT,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_members_name_active
    ON members(display_name, active);

CREATE TABLE IF NOT EXISTS trips (
    id                       TEXT PRIMARY KEY,
    name                     TEXT NOT NULL,
    start_date               TEXT NOT NULL,
    end_date                 TEXT,
    status                   TEXT NOT NULL,
    expected_member_count    INTEGER NOT NULL,
    initial_topup_per_member INTEGER,
    sheet_id                 TEXT,
    sheet_url                TEXT,
    created_by               TEXT NOT NULL REFERENCES members(id),
    created_at               TEXT NOT NULL,
    settled_at               TEXT,
    archived_at              TEXT
);

CREATE INDEX IF NOT EXISTS idx_trips_status ON trips(status);

CREATE TABLE IF NOT EXISTS trip_members (
    trip_id    TEXT NOT NULL REFERENCES trips(id),
    member_id  TEXT NOT NULL REFERENCES members(id),
    joined_at  TEXT NOT NULL,
    left_at    TEXT,
    PRIMARY KEY (trip_id, member_id)
);

CREATE TABLE IF NOT EXISTS contributions (
    id                 TEXT PRIMARY KEY,
    trip_id            TEXT NOT NULL REFERENCES trips(id),
    member_id          TEXT NOT NULL REFERENCES members(id),
    amount_vnd         INTEGER NOT NULL CHECK(amount_vnd > 0),
    kind               TEXT NOT NULL,
    linked_expense_id  TEXT REFERENCES expenses(id),
    note               TEXT,
    occurred_at        TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    confirmed_at       TEXT NOT NULL,
    source_event_id    TEXT UNIQUE,
    trace_id           TEXT,
    status             TEXT NOT NULL DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_contributions_trip
    ON contributions(trip_id, status);
CREATE INDEX IF NOT EXISTS idx_contributions_link
    ON contributions(linked_expense_id)
    WHERE linked_expense_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS expenses (
    id                TEXT PRIMARY KEY,
    trip_id           TEXT NOT NULL REFERENCES trips(id),
    payer_id          TEXT NOT NULL REFERENCES members(id),
    amount_vnd        INTEGER NOT NULL CHECK(amount_vnd > 0),
    category          TEXT NOT NULL,
    description       TEXT NOT NULL,
    split_method      TEXT NOT NULL DEFAULT 'equal',
    split_member_ids  TEXT NOT NULL,
    source            TEXT NOT NULL,
    source_raw        TEXT,
    ocr_confidence    REAL,
    occurred_at       TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    confirmed_at      TEXT NOT NULL,
    confirmed_by      TEXT NOT NULL REFERENCES members(id),
    source_event_id   TEXT UNIQUE,
    trace_id          TEXT,
    status            TEXT NOT NULL DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_expenses_trip
    ON expenses(trip_id, status);

CREATE TABLE IF NOT EXISTS pending_confirmations (
    id            TEXT PRIMARY KEY,
    zalo_user_id  TEXT NOT NULL,
    trip_id       TEXT REFERENCES trips(id),
    kind          TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'awaiting_confirm',
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pending_expires
    ON pending_confirmations(expires_at);

CREATE TABLE IF NOT EXISTS conversations (
    zalo_user_id    TEXT PRIMARY KEY,
    state           TEXT NOT NULL DEFAULT 'idle',
    pending_id      TEXT REFERENCES pending_confirmations(id),
    active_trip_id  TEXT REFERENCES trips(id),
    last_active_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_events (
    event_id      TEXT PRIMARY KEY,
    processed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sheet_outbox (
    id            TEXT PRIMARY KEY,
    trip_id       TEXT NOT NULL REFERENCES trips(id),
    op            TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    created_at    TEXT NOT NULL,
    processed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON sheet_outbox(status, created_at)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS audit_log (
    id            TEXT PRIMARY KEY,
    ts            TEXT NOT NULL,
    trip_id       TEXT REFERENCES trips(id),
    actor_id      TEXT,
    action        TEXT NOT NULL,
    entity_id     TEXT,
    details_json  TEXT,
    trace_id      TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_trip   ON audit_log(trip_id);
CREATE INDEX IF NOT EXISTS idx_audit_trace  ON audit_log(trace_id);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _str_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return dict(row)


class Database:
    """
    Thin async wrapper quanh aiosqlite.
    Dùng dependency injection — không dùng global instance.
    """

    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        log.info("db.connected", path=self._path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def init_schema(self) -> None:
        """Chạy SCHEMA_SQL để tạo bảng nếu chưa có."""
        assert self._conn, "call connect() first"
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
        log.info("db.schema_initialized")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Atomic transaction. Rollback tự động nếu có exception."""
        assert self._conn
        async with self._conn:  # aiosqlite context manager = commit/rollback
            yield

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        assert self._conn
        return await self._conn.execute(sql, params)

    async def executemany(self, sql: str, params_list: list[tuple]) -> None:
        assert self._conn
        await self._conn.executemany(sql, params_list)

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        assert self._conn
        cursor = await self._conn.execute(sql, params)
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        assert self._conn
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    # ── Settings (runtime flags, e.g. bot_enabled) ─────────────────────────

    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self.fetch_one(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await self._conn.commit()

    # ── Idempotency ─────────────────────────────────────────────────────────

    async def is_event_processed(self, event_id: str) -> bool:
        row = await self.fetch_one(
            "SELECT event_id FROM processed_events WHERE event_id = ?",
            (event_id,),
        )
        return row is not None

    async def mark_event_processed(self, event_id: str) -> None:
        await self.execute(
            "INSERT OR IGNORE INTO processed_events(event_id, processed_at) VALUES(?,?)",
            (event_id, datetime.utcnow().isoformat()),
        )


# ── Singleton factory (wired in main.py) ────────────────────────────────────

_db_instance: Database | None = None


def get_db() -> Database:
    assert _db_instance is not None, "Database not initialized"
    return _db_instance


async def init_db(db_path: str) -> Database:
    global _db_instance
    db = Database(db_path)
    await db.connect()
    await db.init_schema()
    _db_instance = db
    return db
