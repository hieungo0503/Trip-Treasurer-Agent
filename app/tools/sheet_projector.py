"""
Sheet outbox projector — xử lý sheet_outbox async.

Pattern: DB outbox → projector poll → Google Sheets write.
Phase 1: stub no-op.
Phase 2: loop chạy nền, consume outbox, gọi sheets.py.
"""

from __future__ import annotations

import asyncio

import structlog

from app.storage.db import get_db
from app.storage.repositories import SheetOutboxRepository

log = structlog.get_logger()

_running = False


async def run_projector_once() -> int:
    """
    Xử lý tất cả pending outbox entries.
    Trả về số entries đã xử lý.
    Phase 1: mark done ngay mà không gọi Sheets API.
    """
    db = get_db()
    outbox_repo = SheetOutboxRepository(db)
    entries = await outbox_repo.list_pending(limit=50)

    processed = 0
    for entry in entries:
        try:
            # Phase 2: dispatch theo entry["op"] → sheets.py
            log.debug("sheet_projector.skip_stub", op=entry["op"], id=entry["id"])
            await outbox_repo.mark_done(entry["id"])
            processed += 1
        except Exception as e:
            await outbox_repo.mark_failed(entry["id"], str(e))

    if processed:
        await db._conn.commit()

    return processed


async def start_projector_loop(interval_seconds: int = 30) -> None:
    """Background loop — gọi từ startup event của FastAPI."""
    global _running
    _running = True
    log.info("sheet_projector.started", interval=interval_seconds)
    while _running:
        try:
            n = await run_projector_once()
            if n:
                log.info("sheet_projector.processed", count=n)
        except Exception as e:
            log.error("sheet_projector.loop_error", error=str(e))
        await asyncio.sleep(interval_seconds)


def stop_projector() -> None:
    global _running
    _running = False
