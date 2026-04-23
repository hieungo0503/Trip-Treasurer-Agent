"""
Google Sheets write client — Phase 2.

Viết vào sheet theo pattern outbox:
  DB commit → sheet_outbox → sheet_projector poll → sheets.py ghi

Sheet structure (1 sheet per trip, 3 tabs):
  Tab 1: "Chi tiêu"        — expenses
  Tab 2: "Nạp & Ứng"       — contributions
  Tab 3: "Tổng kết"        — summary / settlement

Tất cả writes dùng valueInputOption=RAW (không USER_ENTERED)
để tránh Google tự parse số/ngày sai.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Optional

import structlog
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account

from app.config import get_settings
from app.observability.metrics import sheet_api_calls_total, sheets_append_total
from app.reliability.circuit_breaker import sheets_circuit
from app.reliability.retry import sheets_retry

log = structlog.get_logger()

# Tab names
TAB_EXPENSES = "Chi tiêu"
TAB_CONTRIBUTIONS = "Nạp & Ứng"
TAB_SUMMARY = "Tổng kết"

# Column headers
EXPENSE_HEADERS = [
    "ID", "Ngày", "Người trả", "Số tiền (VNĐ)", "Danh mục",
    "Mô tả", "Nguồn", "Trạng thái",
]
CONTRIBUTION_HEADERS = [
    "ID", "Ngày", "Thành viên", "Số tiền (VNĐ)", "Loại",
    "Chi tiêu liên kết", "Ghi chú", "Trạng thái",
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]


# ── Credentials & client factory ──────────────────────────────────────────────

def _build_sheets_service():
    """Build Google Sheets API service từ service account JSON."""
    settings = get_settings()
    sa_path = settings.google_service_account_json

    if not sa_path or not os.path.exists(sa_path):
        raise RuntimeError(
            f"Google service account JSON not found: {sa_path}. "
            "Set GOOGLE_SERVICE_ACCOUNT_JSON in .env"
        )

    creds = service_account.Credentials.from_service_account_file(
        sa_path,
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


_sheets_service = None


def get_sheets_service():
    """Lazy singleton — build service lần đầu."""
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = _build_sheets_service()
    return _sheets_service


def reset_sheets_service() -> None:
    """Reset service (dùng trong test để inject mock)."""
    global _sheets_service
    _sheets_service = None


def set_sheets_service(svc) -> None:
    """Inject mock service cho tests."""
    global _sheets_service
    _sheets_service = svc


# ── Internal helpers ──────────────────────────────────────────────────────────

def _range(tab: str, start_col: str = "A", end_col: str = "Z") -> str:
    return f"'{tab}'!{start_col}:{end_col}"


def _row_range(tab: str, row: int) -> str:
    return f"'{tab}'!A{row}:Z{row}"


def _handle_http_error(e: HttpError, op: str, sheet_id: str) -> None:
    """Log và re-raise HttpError từ Google API."""
    log.error(
        "sheets.api_error",
        op=op,
        sheet_id=sheet_id,
        status=e.resp.status,
        reason=e.reason,
    )
    raise


# ── Public API ────────────────────────────────────────────────────────────────

@sheets_retry
async def append_expense_row(sheet_id: str, row: dict) -> None:
    """
    Append 1 dòng expense vào tab "Chi tiêu".

    row keys: id, occurred_at, payer_name, amount_vnd, category,
              description, source, status
    """
    if not sheet_id:
        log.warning("sheets.append_expense.no_sheet_id")
        return

    if not sheets_circuit.can_attempt():
        log.warning("sheets.circuit_open", op="append_expense", sheet_id=sheet_id)
        sheets_append_total.labels(op="expense", status="circuit_open").inc()
        return

    values = [[
        row.get("id", ""),
        row.get("occurred_at", ""),
        row.get("payer_name", ""),
        row.get("amount_vnd", 0),
        row.get("category", ""),
        row.get("description", ""),
        row.get("source", ""),
        row.get("status", "active"),
    ]]

    try:
        svc = get_sheets_service()
        svc.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=_range(TAB_EXPENSES),
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()
        sheets_circuit.record_success()
        sheet_api_calls_total.labels(operation="append_expense").inc()
        sheets_append_total.labels(op="expense", status="ok").inc()
        log.info("sheets.append_expense.ok", sheet_id=sheet_id, expense_id=row.get("id"))
    except HttpError as e:
        sheets_circuit.record_failure()
        sheets_append_total.labels(op="expense", status="error").inc()
        _handle_http_error(e, "append_expense", sheet_id)
    except Exception as e:
        sheets_circuit.record_failure()
        sheets_append_total.labels(op="expense", status="error").inc()
        log.error("sheets.append_expense.error", sheet_id=sheet_id, error=str(e))
        raise


@sheets_retry
async def append_contribution_row(sheet_id: str, row: dict) -> None:
    """
    Append 1 dòng contribution vào tab "Nạp & Ứng".

    row keys: id, occurred_at, member_name, amount_vnd, kind,
              linked_expense_id, note, status
    """
    if not sheet_id:
        log.warning("sheets.append_contribution.no_sheet_id")
        return

    if not sheets_circuit.can_attempt():
        log.warning("sheets.circuit_open", op="append_contribution", sheet_id=sheet_id)
        sheets_append_total.labels(op="contribution", status="circuit_open").inc()
        return

    values = [[
        row.get("id", ""),
        row.get("occurred_at", ""),
        row.get("member_name", ""),
        row.get("amount_vnd", 0),
        row.get("kind", ""),
        row.get("linked_expense_id", ""),
        row.get("note", ""),
        row.get("status", "active"),
    ]]

    try:
        svc = get_sheets_service()
        svc.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=_range(TAB_CONTRIBUTIONS),
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()
        sheets_circuit.record_success()
        sheet_api_calls_total.labels(operation="append_contribution").inc()
        sheets_append_total.labels(op="contribution", status="ok").inc()
        log.info("sheets.append_contribution.ok", sheet_id=sheet_id, contrib_id=row.get("id"))
    except HttpError as e:
        sheets_circuit.record_failure()
        sheets_append_total.labels(op="contribution", status="error").inc()
        _handle_http_error(e, "append_contribution", sheet_id)
    except Exception as e:
        sheets_circuit.record_failure()
        sheets_append_total.labels(op="contribution", status="error").inc()
        log.error("sheets.append_contribution.error", sheet_id=sheet_id, error=str(e))
        raise


@sheets_retry
async def rebuild_sheet_from_db(
    sheet_id: str,
    trip_id: str,
    expenses: list[dict],
    contributions: list[dict],
) -> None:
    """
    Rebuild toàn bộ sheet từ DB (dùng khi /rebuild_sheet).

    Clears cả 2 tab rồi ghi lại từ đầu với batchUpdate.
    """
    if not sheet_id:
        log.warning("sheets.rebuild.no_sheet_id", trip_id=trip_id)
        return

    if not sheets_circuit.can_attempt():
        log.warning("sheets.circuit_open", op="rebuild", sheet_id=sheet_id)
        return

    # Build data cho cả 2 tab
    expense_rows = [EXPENSE_HEADERS] + [
        [
            e.get("id", ""),
            e.get("occurred_at", ""),
            e.get("payer_name", ""),
            e.get("amount_vnd", 0),
            e.get("category", ""),
            e.get("description", ""),
            e.get("source", ""),
            e.get("status", "active"),
        ]
        for e in expenses
    ]

    contrib_rows = [CONTRIBUTION_HEADERS] + [
        [
            c.get("id", ""),
            c.get("occurred_at", ""),
            c.get("member_name", ""),
            c.get("amount_vnd", 0),
            c.get("kind", ""),
            c.get("linked_expense_id", ""),
            c.get("note", ""),
            c.get("status", "active"),
        ]
        for c in contributions
    ]

    batch_data = [
        {
            "range": _range(TAB_EXPENSES),
            "values": expense_rows,
        },
        {
            "range": _range(TAB_CONTRIBUTIONS),
            "values": contrib_rows,
        },
    ]

    try:
        svc = get_sheets_service()

        # Clear cả 2 tab trước
        svc.spreadsheets().values().batchClear(
            spreadsheetId=sheet_id,
            body={
                "ranges": [
                    _range(TAB_EXPENSES),
                    _range(TAB_CONTRIBUTIONS),
                ]
            },
        ).execute()

        # Ghi lại data
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id,
            body={
                "valueInputOption": "RAW",
                "data": batch_data,
            },
        ).execute()

        sheets_circuit.record_success()
        sheet_api_calls_total.labels(operation="rebuild_sheet").inc()
        log.info(
            "sheets.rebuild.ok",
            sheet_id=sheet_id,
            trip_id=trip_id,
            expenses=len(expenses),
            contributions=len(contributions),
        )
    except HttpError as e:
        sheets_circuit.record_failure()
        _handle_http_error(e, "rebuild_sheet", sheet_id)
    except Exception as e:
        sheets_circuit.record_failure()
        log.error("sheets.rebuild.error", sheet_id=sheet_id, trip_id=trip_id, error=str(e))
        raise


@sheets_retry
async def update_summary_tab(sheet_id: str, summary: dict) -> None:
    """
    Cập nhật tab "Tổng kết" với fund balance, settlement plan.

    summary keys:
        trip_name, trip_id, fund_balance, total_expense,
        settlement_rows (list of {from, to, amount})
        members (list of {name, net_balance})
    """
    if not sheet_id:
        log.warning("sheets.update_summary.no_sheet_id")
        return

    if not sheets_circuit.can_attempt():
        log.warning("sheets.circuit_open", op="update_summary", sheet_id=sheet_id)
        return

    rows: list[list[Any]] = [
        ["Trip", summary.get("trip_name", "")],
        ["ID", summary.get("trip_id", "")],
        ["Tổng quỹ (VNĐ)", summary.get("fund_balance", 0)],
        ["Tổng chi (VNĐ)", summary.get("total_expense", 0)],
        [],
        ["=== Số dư theo người ==="],
        ["Thành viên", "Số dư (VNĐ)", "Nhận(+)/Trả(-)"],
    ]

    for m in summary.get("members", []):
        net = m.get("net_balance", 0)
        rows.append([m.get("name", ""), net, "Nhận" if net > 0 else ("Trả" if net < 0 else "Hoà")])

    rows.append([])
    rows.append(["=== Kế hoạch thanh toán ==="])
    rows.append(["Người trả", "Người nhận", "Số tiền (VNĐ)"])

    for s in summary.get("settlement_rows", []):
        rows.append([s.get("from", ""), s.get("to", ""), s.get("amount", 0)])

    try:
        svc = get_sheets_service()

        svc.spreadsheets().values().batchClear(
            spreadsheetId=sheet_id,
            body={"ranges": [_range(TAB_SUMMARY)]},
        ).execute()

        svc.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"'{TAB_SUMMARY}'!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()

        sheets_circuit.record_success()
        sheet_api_calls_total.labels(operation="update_summary").inc()
        log.info("sheets.update_summary.ok", sheet_id=sheet_id, trip_id=summary.get("trip_id"))
    except HttpError as e:
        sheets_circuit.record_failure()
        _handle_http_error(e, "update_summary", sheet_id)
    except Exception as e:
        sheets_circuit.record_failure()
        log.error("sheets.update_summary.error", sheet_id=sheet_id, error=str(e))
        raise


async def ensure_headers(sheet_id: str) -> None:
    """
    Ghi header row vào cả 2 tab nếu chưa có.
    Gọi khi provision sheet mới.
    """
    if not sheet_id:
        return

    try:
        svc = get_sheets_service()
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id,
            body={
                "valueInputOption": "RAW",
                "data": [
                    {
                        "range": f"'{TAB_EXPENSES}'!A1",
                        "values": [EXPENSE_HEADERS],
                    },
                    {
                        "range": f"'{TAB_CONTRIBUTIONS}'!A1",
                        "values": [CONTRIBUTION_HEADERS],
                    },
                ],
            },
        ).execute()
        log.info("sheets.ensure_headers.ok", sheet_id=sheet_id)
    except Exception as e:
        log.error("sheets.ensure_headers.error", sheet_id=sheet_id, error=str(e))
        raise
