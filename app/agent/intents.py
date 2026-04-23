"""
Intent classifier — rule-based trước, LLM fallback sau.

80% tin nhắn phân loại bằng regex mà không cần gọi LLM.
Thứ tự kiểm tra quan trọng: command → state-dependent → domain-specific → fallback.
"""

from __future__ import annotations

import re
from enum import Enum

from app.domain.models import ConversationState, TripStatus


class Intent(str, Enum):
    # Trip lifecycle
    TRIP_NEW = "trip_new"
    TRIP_LIST = "trip_list"
    TRIP_VIEW = "trip_view"
    TRIP_SWITCH = "trip_switch"
    TRIP_END = "trip_end"
    TRIP_ARCHIVE = "trip_archive"
    TRIP_EXPORT = "trip_export"
    TRIP_PURGE = "trip_purge"
    TRIP_PROVISION_SHEET = "trip_provision_sheet"

    # Ghi nhận tài chính
    LOG_EXPENSE = "log_expense"
    LOG_EXPENSE_IMAGE = "log_expense_image"
    LOG_TOPUP = "log_topup"
    LOG_INITIAL_TOPUP = "log_initial_topup"
    LOG_ADVANCE_EXPENSE = "log_advance_expense"

    # Query
    QUERY_FUND = "query_fund"
    QUERY_SUMMARY = "query_summary"
    QUERY_MINE = "query_mine"
    QUERY_TOPUP_MINE = "query_topup_mine"
    QUERY_SETTLEMENT = "query_settlement"

    # Confirmation flow
    CONFIRM = "confirm"
    AMEND = "amend"
    CANCEL_PENDING = "cancel_pending"

    # Admin actions
    HUY_AUTO_ADVANCE = "huy_auto_advance"
    REBUILD_SHEET = "rebuild_sheet"
    DELETE_DATA = "delete_data"
    PAUSE_BOT = "pause_bot"
    RESUME_BOT = "resume_bot"

    # Help
    HELP_OVERVIEW = "help_overview"
    HELP_TOPIC = "help_topic"
    HELP_SHARE = "help_share"

    # Welcome (user mới)
    WELCOME = "welcome"

    # LLM sẽ phân loại tiếp
    UNKNOWN = "unknown"


def classify_intent(
    text: str,
    state: ConversationState = ConversationState.IDLE,
    trip_status: TripStatus | None = None,
    is_image: bool = False,
    is_new_user: bool = False,
) -> Intent:
    """
    Phân loại intent từ tin nhắn user.

    Args:
        text: nội dung tin nhắn (đã strip)
        state: trạng thái conversation hiện tại
        trip_status: trạng thái trip đang active (None nếu không có)
        is_image: True nếu user gửi ảnh
        is_new_user: True nếu user chưa có trong members

    Returns:
        Intent — nếu UNKNOWN, orchestrator sẽ gọi LLM
    """
    if is_image:
        return Intent.LOG_EXPENSE_IMAGE

    t = text.strip()
    tl = t.lower()

    # AWAITING_CONFIRM phải check trước is_new_user: user mới đang chờ confirm
    # (vd: vừa gửi "Hà đã nạp 500k") cũng cần "ok"/"huỷ" được nhận đúng.
    if state == ConversationState.AWAITING_CONFIRM:
        if re.match(r"^(ok|oke|okay|đồng ý|xác nhận|✅|khởi động)$", tl):
            return Intent.CONFIRM
        if tl.startswith("sửa "):
            return Intent.AMEND
        if re.match(r"^(huỷ|huy|cancel|❌|bỏ qua)$", tl):
            return Intent.CANCEL_PENDING

    # ── Commands (slash commands — exact hoặc startswith) ──────────────────
    # Phải check TRƯỚC is_new_user: admin gõ /trip_new lần đầu vẫn là new user.
    if tl.startswith("/trip_new"):
        return Intent.TRIP_NEW
    if tl in ("/trips",):
        return Intent.TRIP_LIST
    if re.match(r"^/trip_view\b", tl):
        return Intent.TRIP_VIEW
    if re.match(r"^/trip_switch\b", tl):
        return Intent.TRIP_SWITCH
    if re.match(r"^/trip_end\b", tl):
        return Intent.TRIP_END
    if re.match(r"^/trip_archive\b", tl):
        return Intent.TRIP_ARCHIVE
    if re.match(r"^/trip_export\b", tl):
        return Intent.TRIP_EXPORT
    if re.match(r"^/trip_purge\b", tl):
        return Intent.TRIP_PURGE
    if re.match(r"^/trip_provision_sheet\b", tl):
        return Intent.TRIP_PROVISION_SHEET

    # Query commands
    if tl in ("/quy", "/quỹ"):
        return Intent.QUERY_FUND
    if tl in ("/tongket", "/tổng kết", "/tongket"):
        return Intent.QUERY_SUMMARY
    if tl in ("/cuatoi", "/của tôi"):
        return Intent.QUERY_MINE
    if tl in ("/nap_cua_toi", "/nạp_của_tôi", "/nap_cua_toi"):
        return Intent.QUERY_TOPUP_MINE
    if tl in ("/chiaai", "/chia ai"):
        return Intent.QUERY_SETTLEMENT

    # Action commands
    if re.match(r"^/huy_auto\b", tl):
        return Intent.HUY_AUTO_ADVANCE
    if tl in ("/rebuild_sheet",):
        return Intent.REBUILD_SHEET
    if tl in ("/xoadulieu", "/xoá dữ liệu"):
        return Intent.DELETE_DATA
    if tl in ("/pause_bot",):
        return Intent.PAUSE_BOT
    if tl in ("/resume_bot",):
        return Intent.RESUME_BOT

    # Help commands
    if tl in ("/help", "/lenh", "/lệnh", "/menu"):
        return Intent.HELP_OVERVIEW
    if re.match(r"^/help\s+\S", tl):
        return Intent.HELP_TOPIC
    if tl in ("/share",):
        return Intent.HELP_SHARE

    # ── is_new_user: sau slash commands để /trip_new không bị chặn ──────────
    if is_new_user and trip_status == TripStatus.COLLECTING_TOPUP:
        if re.search(r"[\wÀ-ỹ]+\s+(đã\s+nạp|góp|nạp|đã\s+góp)\s+\d", tl):
            return Intent.LOG_INITIAL_TOPUP
    if is_new_user:
        return Intent.WELCOME

    # ── State-dependent: AWAITING_CONFIRM ─────────────────────────────────
    if state == ConversationState.AWAITING_CONFIRM:
        if re.match(r"^(ok|oke|okay|đồng ý|xác nhận|✅|khởi động)$", tl):
            return Intent.CONFIRM
        if tl.startswith("sửa "):
            return Intent.AMEND
        if re.match(r"^(huỷ|huy|cancel|❌|bỏ qua)$", tl):
            return Intent.CANCEL_PENDING

    # ── COLLECTING_TOPUP: "<tên> đã nạp X" ───────────────────────────────
    if trip_status == TripStatus.COLLECTING_TOPUP:
        if re.search(r"[\wÀ-ỹ]+\s+(đã\s+nạp|góp|nạp|đã\s+góp)\s+\d", tl):
            return Intent.LOG_INITIAL_TOPUP

    # ── Advance expense: "ứng X để chi Y" ────────────────────────────────
    if re.search(r"ứng\s+\d.*(để\s+chi|để\s+trả|để\s+góp|cho\b|trả\b)", tl):
        return Intent.LOG_ADVANCE_EXPENSE

    # ── Topup: "nạp X" / "góp X" (không có "để") ─────────────────────────
    if re.search(r"^(nạp|góp|nap|gop)\s+\d", tl) and "để" not in tl:
        return Intent.LOG_TOPUP

    # ── Expense: "chi X" / "trả X" / số tiền đầu câu ─────────────────────
    if re.search(r"(chi|trả|tra|thanh\s*toán)\s+\d", tl):
        return Intent.LOG_EXPENSE
    if re.match(r"^\d+\s*[kKtTmM]", t):
        return Intent.LOG_EXPENSE

    # ── Help keywords tự nhiên ────────────────────────────────────────────
    if any(
        kw in tl
        for kw in ["hướng dẫn", "help", "làm sao", "cách dùng", "không biết", "hỗ trợ"]
    ):
        return Intent.HELP_OVERVIEW

    return Intent.UNKNOWN


# ── Extract slash command argument ────────────────────────────────────────────

def extract_command_arg(text: str, command: str) -> str:
    """
    Lấy phần sau slash command.
    VD: "/trip_view TRIP-20260510" → "TRIP-20260510"
    """
    stripped = text.strip()
    if stripped.lower().startswith(command.lower()):
        return stripped[len(command):].strip()
    return ""
