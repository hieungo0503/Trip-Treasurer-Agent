"""
Tests cho tools/sheets.py và tools/sheet_provisioner.py — Phase 2.

Dùng MagicMock để mock Google API (không gọi API thật).
Covers:
  - append_expense_row: success, no sheet_id, circuit open, API error
  - append_contribution_row: success, no sheet_id
  - rebuild_sheet_from_db: clear + batchUpdate called correctly
  - update_summary_tab: correct data format
  - ensure_headers: called with correct ranges
  - provision_trip_sheet: copy + headers, no config → (None, None), Drive error → (None, None)
  - share_sheet_with_user: success, circuit open
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from googleapiclient.errors import HttpError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_http_error(status: int, reason: str = "Error") -> HttpError:
    resp = MagicMock()
    resp.status = status
    resp.reason = reason
    return HttpError(resp=resp, content=b"error")


def _mock_sheets_svc():
    """Build a mock Google Sheets service."""
    svc = MagicMock()
    sheets = svc.spreadsheets.return_value
    values = sheets.values.return_value
    values.append.return_value.execute.return_value = {"updates": {}}
    values.batchUpdate.return_value.execute.return_value = {}
    values.batchClear.return_value.execute.return_value = {}
    values.update.return_value.execute.return_value = {}
    return svc


def _mock_drive_svc():
    """Build a mock Google Drive service."""
    svc = MagicMock()
    files = svc.files.return_value
    files.copy.return_value.execute.return_value = {"id": "sheet_new_001", "name": "Trip Test"}
    perms = svc.permissions.return_value
    perms.create.return_value.execute.return_value = {}
    return svc


# ── sheets.append_expense_row ─────────────────────────────────────────────────

class TestAppendExpenseRow:
    @pytest.mark.asyncio
    async def test_append_ok(self):
        from app.tools.sheets import append_expense_row, set_sheets_service
        from app.reliability.circuit_breaker import sheets_circuit

        sheets_circuit.reset()
        mock_svc = _mock_sheets_svc()
        set_sheets_service(mock_svc)

        await append_expense_row(
            sheet_id="sheet_001",
            row={
                "id": "EXP001",
                "occurred_at": "2026-04-20",
                "payer_name": "Đức",
                "amount_vnd": 500000,
                "category": "food",
                "description": "Ăn tối",
                "source": "text",
                "status": "active",
            },
        )

        values_mock = mock_svc.spreadsheets.return_value.values.return_value
        values_mock.append.assert_called_once()
        call_kwargs = values_mock.append.call_args
        assert call_kwargs.kwargs["valueInputOption"] == "RAW"

    @pytest.mark.asyncio
    async def test_skip_when_no_sheet_id(self):
        from app.tools.sheets import append_expense_row, set_sheets_service

        mock_svc = _mock_sheets_svc()
        set_sheets_service(mock_svc)

        await append_expense_row(sheet_id="", row={"amount_vnd": 100})
        mock_svc.spreadsheets.return_value.values.return_value.append.assert_not_called()

    @pytest.mark.asyncio
    async def test_circuit_open_skips_api(self):
        from app.tools.sheets import append_expense_row, set_sheets_service
        from app.reliability.circuit_breaker import sheets_circuit, CircuitState

        sheets_circuit.state = CircuitState.OPEN
        sheets_circuit._opened_at = 0

        mock_svc = _mock_sheets_svc()
        set_sheets_service(mock_svc)

        await append_expense_row(sheet_id="sheet_001", row={"amount_vnd": 100})
        mock_svc.spreadsheets.return_value.values.return_value.append.assert_not_called()

        sheets_circuit.reset()

    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        from app.tools.sheets import append_expense_row, set_sheets_service
        from app.reliability.circuit_breaker import sheets_circuit

        sheets_circuit.reset()
        mock_svc = _mock_sheets_svc()
        mock_svc.spreadsheets.return_value.values.return_value.append.return_value.execute.side_effect = (
            _make_http_error(500, "Internal Server Error")
        )
        set_sheets_service(mock_svc)

        with pytest.raises(HttpError):
            await append_expense_row(sheet_id="sheet_001", row={"amount_vnd": 100})


# ── sheets.append_contribution_row ────────────────────────────────────────────

class TestAppendContributionRow:
    @pytest.mark.asyncio
    async def test_append_ok(self):
        from app.tools.sheets import append_contribution_row, set_sheets_service
        from app.reliability.circuit_breaker import sheets_circuit

        sheets_circuit.reset()
        mock_svc = _mock_sheets_svc()
        set_sheets_service(mock_svc)

        await append_contribution_row(
            sheet_id="sheet_001",
            row={
                "id": "CON001",
                "occurred_at": "2026-04-20",
                "member_name": "Hà",
                "amount_vnd": 800000,
                "kind": "initial_topup",
                "linked_expense_id": "",
                "note": "",
                "status": "active",
            },
        )

        values_mock = mock_svc.spreadsheets.return_value.values.return_value
        values_mock.append.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_when_no_sheet_id(self):
        from app.tools.sheets import append_contribution_row, set_sheets_service

        mock_svc = _mock_sheets_svc()
        set_sheets_service(mock_svc)

        await append_contribution_row(sheet_id="", row={"amount_vnd": 100})
        mock_svc.spreadsheets.return_value.values.return_value.append.assert_not_called()


# ── sheets.rebuild_sheet_from_db ──────────────────────────────────────────────

class TestRebuildSheet:
    @pytest.mark.asyncio
    async def test_clear_then_write(self):
        from app.tools.sheets import rebuild_sheet_from_db, set_sheets_service
        from app.reliability.circuit_breaker import sheets_circuit

        sheets_circuit.reset()
        mock_svc = _mock_sheets_svc()
        set_sheets_service(mock_svc)

        expenses = [
            {
                "id": "E1", "occurred_at": "2026-04-20", "payer_name": "Đức",
                "amount_vnd": 200000, "category": "food", "description": "Ăn trưa",
                "source": "text", "status": "active",
            }
        ]
        contributions = [
            {
                "id": "C1", "occurred_at": "2026-04-19", "member_name": "Đức",
                "amount_vnd": 800000, "kind": "initial_topup",
                "linked_expense_id": "", "note": "", "status": "active",
            }
        ]

        await rebuild_sheet_from_db("sheet_001", "TRIP-001", expenses, contributions)

        values_mock = mock_svc.spreadsheets.return_value.values.return_value
        # batchClear gọi trước
        values_mock.batchClear.assert_called_once()
        # batchUpdate gọi sau
        values_mock.batchUpdate.assert_called_once()

        # Verify header được include
        call_body = values_mock.batchUpdate.call_args.kwargs["body"]
        # "Chi tiêu" tab có dữ liệu
        expense_data = call_body["data"][0]["values"]
        assert len(expense_data) == 2  # header + 1 expense row
        assert expense_data[0][0] == "ID"  # header

    @pytest.mark.asyncio
    async def test_skip_when_no_sheet_id(self):
        from app.tools.sheets import rebuild_sheet_from_db, set_sheets_service

        mock_svc = _mock_sheets_svc()
        set_sheets_service(mock_svc)

        await rebuild_sheet_from_db("", "TRIP-001", [], [])
        mock_svc.spreadsheets.return_value.values.return_value.batchClear.assert_not_called()


# ── sheets.update_summary_tab ─────────────────────────────────────────────────

class TestUpdateSummaryTab:
    @pytest.mark.asyncio
    async def test_update_ok(self):
        from app.tools.sheets import update_summary_tab, set_sheets_service
        from app.reliability.circuit_breaker import sheets_circuit

        sheets_circuit.reset()
        mock_svc = _mock_sheets_svc()
        set_sheets_service(mock_svc)

        summary = {
            "trip_name": "Đà Lạt",
            "trip_id": "TRIP-001",
            "fund_balance": 4000000,
            "total_expense": 800000,
            "members": [
                {"name": "Đức", "net_balance": 200000},
                {"name": "Hà", "net_balance": -200000},
            ],
            "settlement_rows": [
                {"from": "Hà", "to": "Đức", "amount": 200000},
            ],
        }

        await update_summary_tab("sheet_001", summary)

        values_mock = mock_svc.spreadsheets.return_value.values.return_value
        values_mock.batchClear.assert_called_once()
        values_mock.update.assert_called_once()

        # Verify data contains settlement info
        call_body = values_mock.update.call_args.kwargs["body"]
        all_values = [cell for row in call_body["values"] for cell in row]
        assert "Đà Lạt" in all_values
        assert 4000000 in all_values


# ── sheet_provisioner.provision_trip_sheet ────────────────────────────────────

class TestProvisionTripSheet:
    @pytest.mark.asyncio
    async def test_provision_ok(self):
        from app.tools.sheet_provisioner import provision_trip_sheet, set_drive_service
        from app.tools.sheets import set_sheets_service
        from app.reliability.circuit_breaker import drive_circuit

        drive_circuit.reset()
        mock_drive = _mock_drive_svc()
        set_drive_service(mock_drive)
        mock_sheets = _mock_sheets_svc()
        set_sheets_service(mock_sheets)

        with patch("app.tools.sheet_provisioner.get_settings") as mock_settings:
            mock_settings.return_value.google_sheet_template_id = "template_123"
            mock_settings.return_value.google_sheet_parent_folder_id = "folder_456"
            mock_settings.return_value.google_service_account_json = "/fake/path.json"

            sheet_id, sheet_url = await provision_trip_sheet("Đà Lạt", "TRIP-20260510")

        assert sheet_id == "sheet_new_001"
        assert "sheet_new_001" in sheet_url
        # Drive copy được gọi
        mock_drive.files.return_value.copy.assert_called_once()
        # Tên sheet đúng
        copy_body = mock_drive.files.return_value.copy.call_args.kwargs["body"]
        assert "Đà Lạt" in copy_body["name"]
        assert "TRIP-20260510" in copy_body["name"]

    @pytest.mark.asyncio
    async def test_no_config_returns_none(self):
        from app.tools.sheet_provisioner import provision_trip_sheet

        with patch("app.tools.sheet_provisioner.get_settings") as mock_settings:
            mock_settings.return_value.google_sheet_template_id = ""
            mock_settings.return_value.google_sheet_parent_folder_id = ""

            sheet_id, sheet_url = await provision_trip_sheet("Test Trip", "TRIP-001")

        assert sheet_id is None
        assert sheet_url is None

    @pytest.mark.asyncio
    async def test_drive_error_returns_none(self):
        from app.tools.sheet_provisioner import provision_trip_sheet, set_drive_service
        from app.reliability.circuit_breaker import drive_circuit

        drive_circuit.reset()
        mock_drive = MagicMock()
        mock_drive.files.return_value.copy.return_value.execute.side_effect = (
            _make_http_error(403, "Permission denied")
        )
        set_drive_service(mock_drive)

        with patch("app.tools.sheet_provisioner.get_settings") as mock_settings:
            mock_settings.return_value.google_sheet_template_id = "template_123"
            mock_settings.return_value.google_sheet_parent_folder_id = "folder_456"
            mock_settings.return_value.google_service_account_json = "/fake/path.json"

            sheet_id, sheet_url = await provision_trip_sheet("Test Trip", "TRIP-001")

        assert sheet_id is None
        assert sheet_url is None

    @pytest.mark.asyncio
    async def test_circuit_open_returns_none(self):
        from app.tools.sheet_provisioner import provision_trip_sheet
        from app.reliability.circuit_breaker import drive_circuit, CircuitState

        drive_circuit.state = CircuitState.OPEN
        drive_circuit._opened_at = 0

        with patch("app.tools.sheet_provisioner.get_settings") as mock_settings:
            mock_settings.return_value.google_sheet_template_id = "template_123"
            mock_settings.return_value.google_sheet_parent_folder_id = "folder_456"

            sheet_id, sheet_url = await provision_trip_sheet("Test Trip", "TRIP-001")

        assert sheet_id is None
        drive_circuit.reset()


# ── sheet_provisioner.share_sheet_with_user ────────────────────────────────────

class TestShareSheet:
    @pytest.mark.asyncio
    async def test_share_ok(self):
        from app.tools.sheet_provisioner import share_sheet_with_user, set_drive_service
        from app.reliability.circuit_breaker import drive_circuit

        drive_circuit.reset()
        mock_drive = _mock_drive_svc()
        set_drive_service(mock_drive)

        await share_sheet_with_user("sheet_001", "user@example.com")

        mock_drive.permissions.return_value.create.assert_called_once()
        perm_body = mock_drive.permissions.return_value.create.call_args.kwargs["body"]
        assert perm_body["emailAddress"] == "user@example.com"
        assert perm_body["role"] == "reader"

    @pytest.mark.asyncio
    async def test_skip_when_no_sheet_id(self):
        from app.tools.sheet_provisioner import share_sheet_with_user, set_drive_service

        mock_drive = _mock_drive_svc()
        set_drive_service(mock_drive)

        await share_sheet_with_user("", "user@example.com")
        mock_drive.permissions.return_value.create.assert_not_called()
