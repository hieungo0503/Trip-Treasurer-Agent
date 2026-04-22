"""Repository cho Conversation, PendingConfirmation, SheetOutbox, AuditLog."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional

from app.storage.db import Database


class ConversationRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, zalo_user_id: str) -> Optional[dict]:
        return await self._db.fetch_one(
            "SELECT * FROM conversations WHERE zalo_user_id=?",
            (zalo_user_id,),
        )

    async def upsert(
        self,
        zalo_user_id: str,
        state: str = "idle",
        pending_id: Optional[str] = None,
        active_trip_id: Optional[str] = None,
    ) -> None:
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """
            INSERT INTO conversations(zalo_user_id, state, pending_id, active_trip_id, last_active_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(zalo_user_id) DO UPDATE SET
                state=excluded.state,
                pending_id=excluded.pending_id,
                active_trip_id=excluded.active_trip_id,
                last_active_at=excluded.last_active_at
            """,
            (zalo_user_id, state, pending_id, active_trip_id, now),
        )

    async def set_active_trip(self, zalo_user_id: str, trip_id: Optional[str]) -> None:
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """
            INSERT INTO conversations(zalo_user_id, state, active_trip_id, last_active_at)
            VALUES(?,  'idle', ?, ?)
            ON CONFLICT(zalo_user_id) DO UPDATE SET
                active_trip_id=excluded.active_trip_id,
                last_active_at=excluded.last_active_at
            """,
            (zalo_user_id, trip_id, now),
        )

    async def set_state(
        self,
        zalo_user_id: str,
        state: str,
        pending_id: Optional[str] = None,
    ) -> None:
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """
            INSERT INTO conversations(zalo_user_id, state, pending_id, last_active_at)
            VALUES(?,?,?,?)
            ON CONFLICT(zalo_user_id) DO UPDATE SET
                state=excluded.state,
                pending_id=excluded.pending_id,
                last_active_at=excluded.last_active_at
            """,
            (zalo_user_id, state, pending_id, now),
        )


class PendingRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, pending_id: str) -> Optional[dict]:
        return await self._db.fetch_one(
            "SELECT * FROM pending_confirmations WHERE id=?", (pending_id,)
        )

    async def get_active_for_user(self, zalo_user_id: str) -> Optional[dict]:
        return await self._db.fetch_one(
            """
            SELECT * FROM pending_confirmations
            WHERE zalo_user_id=? AND state='awaiting_confirm'
            ORDER BY created_at DESC LIMIT 1
            """,
            (zalo_user_id,),
        )

    async def insert(
        self,
        zalo_user_id: str,
        kind: str,
        payload: Any,
        expires_at: datetime,
        trip_id: Optional[str] = None,
    ) -> str:
        pending_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """
            INSERT INTO pending_confirmations(
                id, zalo_user_id, trip_id, kind, payload_json,
                state, created_at, expires_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                pending_id, zalo_user_id, trip_id, kind,
                json.dumps(payload) if not isinstance(payload, str) else payload,
                "awaiting_confirm", now, expires_at.isoformat(),
            ),
        )
        return pending_id

    async def confirm(self, pending_id: str) -> None:
        await self._db.execute(
            "UPDATE pending_confirmations SET state='confirmed' WHERE id=?",
            (pending_id,),
        )

    async def cancel(self, pending_id: str) -> None:
        await self._db.execute(
            "UPDATE pending_confirmations SET state='cancelled' WHERE id=?",
            (pending_id,),
        )

    async def delete_expired(self) -> int:
        now = datetime.utcnow().isoformat()
        cursor = await self._db.execute(
            "DELETE FROM pending_confirmations WHERE expires_at < ? AND state='awaiting_confirm'",
            (now,),
        )
        return cursor.rowcount


class SheetOutboxRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(self, trip_id: str, op: str, payload: Any) -> str:
        outbox_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        payload_json = json.dumps(payload) if not isinstance(payload, str) else payload
        await self._db.execute(
            """
            INSERT INTO sheet_outbox(id, trip_id, op, payload_json, status, attempts, created_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (outbox_id, trip_id, op, payload_json, "pending", 0, now),
        )
        return outbox_id

    async def list_pending(self, limit: int = 50) -> list[dict]:
        return await self._db.fetch_all(
            """
            SELECT * FROM sheet_outbox
            WHERE status='pending'
            ORDER BY created_at
            LIMIT ?
            """,
            (limit,),
        )

    async def mark_done(self, outbox_id: str) -> None:
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            "UPDATE sheet_outbox SET status='done', processed_at=? WHERE id=?",
            (now, outbox_id),
        )

    async def mark_failed(self, outbox_id: str, error: str) -> None:
        await self._db.execute(
            """
            UPDATE sheet_outbox
            SET attempts=attempts+1, last_error=?,
                status=CASE WHEN attempts+1 >= 5 THEN 'dead' ELSE 'pending' END
            WHERE id=?
            """,
            (error[:500], outbox_id),
        )


class AuditLogRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self,
        action: str,
        trip_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        details: Optional[dict] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        log_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """
            INSERT INTO audit_log(id, ts, trip_id, actor_id, action,
                                  entity_id, details_json, trace_id)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                log_id, now, trip_id, actor_id, action,
                entity_id,
                json.dumps(details) if details else None,
                trace_id,
            ),
        )
