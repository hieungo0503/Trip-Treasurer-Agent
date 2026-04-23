"""
Google Drive sheet provisioner — Phase 2.

Khi tạo trip mới: copy template spreadsheet → sheet riêng cho trip.

Flow:
  1. drive.files().copy() — duplicate template
  2. drive.files().update() — rename + move vào parent folder
  3. drive.permissions().create() — share với service account (nếu cần)
  4. sheets.ensure_headers() — ghi header row vào 2 tab

Nếu provision fail → trip vẫn được tạo (DB đã commit), chỉ là sheet_id=NULL.
Admin dùng /trip_provision_sheet <trip_id> để retry.
"""

from __future__ import annotations

import os
from typing import Optional

import structlog
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account

from app.config import get_settings
from app.observability.metrics import drive_provision_total, sheet_api_calls_total
from app.reliability.circuit_breaker import drive_circuit
from app.reliability.retry import drive_retry

log = structlog.get_logger()

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

SHEET_URL_TEMPLATE = "https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


# ── Service factory ────────────────────────────────────────────────────────────

_drive_service = None


def _build_drive_service():
    settings = get_settings()
    sa_path = settings.google_service_account_json

    if not sa_path or not os.path.exists(sa_path):
        raise RuntimeError(
            f"Google service account JSON not found: {sa_path}. "
            "Set GOOGLE_SERVICE_ACCOUNT_JSON in .env"
        )

    creds = service_account.Credentials.from_service_account_file(
        sa_path,
        scopes=DRIVE_SCOPES,
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_drive_service():
    global _drive_service
    if _drive_service is None:
        _drive_service = _build_drive_service()
    return _drive_service


def set_drive_service(svc) -> None:
    """Inject mock service cho tests."""
    global _drive_service
    _drive_service = svc


def reset_drive_service() -> None:
    global _drive_service
    _drive_service = None


# ── Public API ────────────────────────────────────────────────────────────────

@drive_retry
async def provision_trip_sheet(
    trip_name: str,
    trip_id: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Copy template → tạo sheet riêng cho trip.

    Returns (sheet_id, sheet_url) nếu thành công.
    Returns (None, None) nếu không có template config hoặc Drive API fail.

    Với Phase 2:
      - Requires GOOGLE_SHEET_TEMPLATE_ID và GOOGLE_SHEET_PARENT_FOLDER_ID trong .env
      - Requires google_service_account_json có quyền Drive Editor trên folder
    """
    settings = get_settings()

    template_id = settings.google_sheet_template_id
    parent_folder_id = settings.google_sheet_parent_folder_id

    if not template_id or not parent_folder_id:
        log.warning(
            "sheet_provisioner.provision.no_config",
            trip_id=trip_id,
            hint="Set GOOGLE_SHEET_TEMPLATE_ID and GOOGLE_SHEET_PARENT_FOLDER_ID in .env",
        )
        return None, None

    if not drive_circuit.can_attempt():
        log.warning("sheet_provisioner.circuit_open", trip_id=trip_id)
        drive_provision_total.labels(status="circuit_open").inc()
        return None, None

    sheet_name = f"Trip {trip_name} [{trip_id}]"

    try:
        drive_svc = get_drive_service()

        # 1. Copy template
        copied = drive_svc.files().copy(
            fileId=template_id,
            body={
                "name": sheet_name,
                "parents": [parent_folder_id],
            },
            fields="id,name",
        ).execute()

        sheet_id: str = copied["id"]
        sheet_url = SHEET_URL_TEMPLATE.format(sheet_id=sheet_id)

        drive_circuit.record_success()
        sheet_api_calls_total.labels(operation="drive_copy_template").inc()

        log.info(
            "sheet_provisioner.provision.ok",
            trip_id=trip_id,
            sheet_id=sheet_id,
            sheet_name=sheet_name,
        )

        # 2. Ghi headers vào các tab (import inline để tránh circular)
        try:
            from app.tools.sheets import ensure_headers
            await ensure_headers(sheet_id)
        except Exception as e:
            # Headers quan trọng nhưng không block trip creation
            log.warning("sheet_provisioner.ensure_headers.failed", sheet_id=sheet_id, error=str(e))

        drive_provision_total.labels(status="ok").inc()
        return sheet_id, sheet_url

    except HttpError as e:
        drive_circuit.record_failure()
        drive_provision_total.labels(status="error").inc()
        log.error(
            "sheet_provisioner.provision.http_error",
            trip_id=trip_id,
            status=e.resp.status,
            reason=e.reason,
        )
        return None, None
    except Exception as e:
        drive_circuit.record_failure()
        drive_provision_total.labels(status="error").inc()
        log.error("sheet_provisioner.provision.error", trip_id=trip_id, error=str(e))
        return None, None


async def share_sheet_with_user(sheet_id: str, email: str) -> None:
    """
    Share sheet với một email cụ thể (quyền Reader).
    Dùng khi admin muốn share sheet cho thành viên qua email.
    """
    if not sheet_id or not email:
        return

    if not drive_circuit.can_attempt():
        log.warning("sheet_provisioner.share.circuit_open", sheet_id=sheet_id)
        return

    try:
        drive_svc = get_drive_service()
        drive_svc.permissions().create(
            fileId=sheet_id,
            body={
                "type": "user",
                "role": "reader",
                "emailAddress": email,
            },
            sendNotificationEmail=False,
        ).execute()
        drive_circuit.record_success()
        sheet_api_calls_total.labels(operation="drive_share").inc()
        log.info("sheet_provisioner.share.ok", sheet_id=sheet_id, email=email)
    except HttpError as e:
        drive_circuit.record_failure()
        log.error(
            "sheet_provisioner.share.http_error",
            sheet_id=sheet_id,
            email=email,
            status=e.resp.status,
            reason=e.reason,
        )
    except Exception as e:
        drive_circuit.record_failure()
        log.error("sheet_provisioner.share.error", sheet_id=sheet_id, email=email, error=str(e))
