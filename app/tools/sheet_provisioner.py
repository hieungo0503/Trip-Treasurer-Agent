"""
Google Drive sheet provisioner — Phase 2.

Khi tạo trip mới: copy template spreadsheet → sheet riêng cho trip.
Phase 1: stub trả về None (no sheet).
Phase 2: implement Drive API copy + share.
"""

from __future__ import annotations

from typing import Optional

import structlog

log = structlog.get_logger()


async def provision_trip_sheet(
    trip_name: str,
    trip_id: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Copy template → sheet mới, trả về (sheet_id, sheet_url).
    Phase 1: trả về (None, None).
    """
    log.info("sheet_provisioner.provision.stub", trip_id=trip_id, trip_name=trip_name)
    return None, None


async def share_sheet_with_user(sheet_id: str, email: str) -> None:
    """Share sheet với user email (Phase 2)."""
    log.info("sheet_provisioner.share.stub", sheet_id=sheet_id, email=email)
