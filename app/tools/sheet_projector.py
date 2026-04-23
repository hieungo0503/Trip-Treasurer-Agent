"""
Sheet outbox projector — xử lý sheet_outbox async.

Pattern: DB commit → sheet_outbox → projector poll → Google Sheets write.

Mỗi entry trong sheet_outbox có:
  - op: string mô tả loại operation
  - payload_json: JSON string với data cần thiết
  - trip_id: để biết sheet nào

ops được hỗ trợ:
  "expense_row"       — append expense vào tab Chi tiêu
  "contribution_row"  — append contribution vào tab Nạp & Ứng
  "rebuild_sheet"     — rebuild toàn bộ sheet từ DB
  "update_summary"    — cập nhật tab Tổng kết
  "provision_sheet"   — retry provision sheet cho trip (Phase 2)
"""

from __future__ import annotations

import asyncio
import json

import structlog

from app.observability.metrics import outbox_pending_gauge
from app.storage.db import get_db
from app.storage.repositories import SheetOutboxRepository

log = structlog.get_logger()

_running = False


# ── Dispatcher ────────────────────────────────────────────────────────────────

async def _dispatch(op: str, payload: dict, trip_id: str) -> None:
    """Route op → đúng sheets/provisioner function."""
    from app.tools import sheets as sheets_mod
    from app.tools import sheet_provisioner as provisioner_mod

    # Lấy sheet_id từ DB (theo trip_id)
    sheet_id: str = payload.get("sheet_id", "")
    if not sheet_id and trip_id:
        sheet_id = await _get_sheet_id_for_trip(trip_id)

    if op == "expense_row":
        await sheets_mod.append_expense_row(sheet_id, payload)

    elif op == "contribution_row":
        await sheets_mod.append_contribution_row(sheet_id, payload)

    elif op == "rebuild_sheet":
        expenses = payload.get("expenses", [])
        contributions = payload.get("contributions", [])
        await sheets_mod.rebuild_sheet_from_db(sheet_id, trip_id, expenses, contributions)

    elif op == "update_summary":
        await sheets_mod.update_summary_tab(sheet_id, payload)

    elif op == "provision_sheet":
        # Retry provision: trip đã tạo nhưng sheet chưa có
        trip_name = payload.get("trip_name", "")
        sheet_id_new, sheet_url = await provisioner_mod.provision_trip_sheet(trip_name, trip_id)
        if sheet_id_new:
            # Update trip record với sheet_id mới
            await _update_trip_sheet(trip_id, sheet_id_new, sheet_url)

    else:
        log.warning("sheet_projector.unknown_op", op=op, trip_id=trip_id)


async def _get_sheet_id_for_trip(trip_id: str) -> str:
    """Lấy sheet_id của trip từ DB."""
    try:
        from app.storage.repositories import TripRepository
        db = get_db()
        repo = TripRepository(db)
        trip = await repo.get_by_id(trip_id)
        if trip and trip.sheet_id:
            return trip.sheet_id
    except Exception as e:
        log.error("sheet_projector.get_sheet_id.error", trip_id=trip_id, error=str(e))
    return ""


async def _update_trip_sheet(trip_id: str, sheet_id: str, sheet_url: str) -> None:
    """Update trip.sheet_id sau khi provision thành công."""
    try:
        db = get_db()
        await db.execute(
            "UPDATE trips SET sheet_id = ?, sheet_url = ? WHERE id = ?",
            (sheet_id, sheet_url, trip_id),
        )
        await db._conn.commit()
        log.info(
            "sheet_projector.trip_sheet_updated",
            trip_id=trip_id,
            sheet_id=sheet_id,
        )
    except Exception as e:
        log.error("sheet_projector.update_trip_sheet.error", trip_id=trip_id, error=str(e))


# ── Main loop ─────────────────────────────────────────────────────────────────

async def run_projector_once() -> int:
    """
    Xử lý tất cả pending outbox entries.
    Trả về số entries đã xử lý thành công.
    """
    db = get_db()
    outbox_repo = SheetOutboxRepository(db)
    entries = await outbox_repo.list_pending(limit=50)

    # Cập nhật gauge
    outbox_pending_gauge.set(len(entries))

    processed = 0
    for entry in entries:
        op = entry["op"]
        trip_id = entry.get("trip_id", "")
        try:
            payload = json.loads(entry.get("payload_json", "{}"))
        except json.JSONDecodeError:
            payload = {}

        try:
            await _dispatch(op, payload, trip_id)
            await outbox_repo.mark_done(entry["id"])
            processed += 1
            log.debug("sheet_projector.entry_done", op=op, id=entry["id"], trip_id=trip_id)
        except Exception as e:
            await outbox_repo.mark_failed(entry["id"], str(e))
            log.error(
                "sheet_projector.entry_failed",
                op=op,
                id=entry["id"],
                trip_id=trip_id,
                error=str(e),
                attempts=entry.get("attempts", 0) + 1,
            )

    if processed:
        try:
            await db._conn.commit()
        except Exception:
            pass

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
