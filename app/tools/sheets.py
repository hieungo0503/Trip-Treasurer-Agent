"""
Google Sheets write client — Phase 2.

Phase 1: stub log-only, không gọi API thật.
Phase 2: implement thật với google-api-python-client.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()


async def append_expense_row(
    sheet_id: str,
    row: dict,
) -> None:
    """Append 1 dòng expense vào sheet (valueInputOption=RAW)."""
    log.info("sheets.append_expense_row.stub", sheet_id=sheet_id, amount=row.get("amount_vnd"))


async def append_contribution_row(
    sheet_id: str,
    row: dict,
) -> None:
    """Append 1 dòng contribution vào sheet."""
    log.info("sheets.append_contribution_row.stub", sheet_id=sheet_id, amount=row.get("amount_vnd"))


async def rebuild_sheet_from_db(
    sheet_id: str,
    trip_id: str,
    expenses: list[dict],
    contributions: list[dict],
) -> None:
    """Rebuild toàn bộ sheet từ DB (dùng khi /rebuild_sheet)."""
    log.info("sheets.rebuild_sheet.stub", sheet_id=sheet_id, trip_id=trip_id)


async def update_summary_tab(
    sheet_id: str,
    summary: dict,
) -> None:
    """Cập nhật tab Summary với fund balance, settlement."""
    log.info("sheets.update_summary_tab.stub", sheet_id=sheet_id)
