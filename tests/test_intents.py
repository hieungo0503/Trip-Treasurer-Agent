"""Tests cho intent classifier."""

import pytest
from app.agent.intents import Intent, classify_intent, extract_command_arg
from app.domain.models import ConversationState, TripStatus


class TestClassifyIntentCommands:
    def test_trip_new(self):
        assert classify_intent("/trip_new Đà Lạt") == Intent.TRIP_NEW

    def test_trip_new_case_insensitive(self):
        assert classify_intent("/TRIP_NEW ...") == Intent.TRIP_NEW

    def test_trips(self):
        assert classify_intent("/trips") == Intent.TRIP_LIST

    def test_trip_view(self):
        assert classify_intent("/trip_view TRIP-123") == Intent.TRIP_VIEW

    def test_trip_switch(self):
        assert classify_intent("/trip_switch TRIP-123") == Intent.TRIP_SWITCH

    def test_trip_end(self):
        assert classify_intent("/trip_end") == Intent.TRIP_END

    def test_trip_archive(self):
        assert classify_intent("/trip_archive TRIP-123") == Intent.TRIP_ARCHIVE

    def test_trip_export(self):
        assert classify_intent("/trip_export TRIP-123") == Intent.TRIP_EXPORT

    def test_trip_purge(self):
        assert classify_intent("/trip_purge TRIP-123") == Intent.TRIP_PURGE

    def test_query_fund(self):
        assert classify_intent("/quy") == Intent.QUERY_FUND

    def test_query_summary(self):
        assert classify_intent("/tongket") == Intent.QUERY_SUMMARY

    def test_query_mine(self):
        assert classify_intent("/cuatoi") == Intent.QUERY_MINE

    def test_query_settlement(self):
        assert classify_intent("/chiaai") == Intent.QUERY_SETTLEMENT

    def test_help(self):
        assert classify_intent("/help") == Intent.HELP_OVERVIEW

    def test_help_lenh(self):
        assert classify_intent("/lenh") == Intent.HELP_OVERVIEW

    def test_help_topic(self):
        assert classify_intent("/help chi-tieu") == Intent.HELP_TOPIC

    def test_help_share(self):
        assert classify_intent("/share") == Intent.HELP_SHARE

    def test_rebuild_sheet(self):
        assert classify_intent("/rebuild_sheet") == Intent.REBUILD_SHEET

    def test_pause_bot(self):
        assert classify_intent("/pause_bot") == Intent.PAUSE_BOT

    def test_resume_bot(self):
        assert classify_intent("/resume_bot") == Intent.RESUME_BOT


class TestClassifyIntentExpense:
    def test_chi_prefix(self):
        assert classify_intent("chi 500k ăn uống") == Intent.LOG_EXPENSE

    def test_tra_prefix(self):
        assert classify_intent("trả 1tr5 khách sạn") == Intent.LOG_EXPENSE

    def test_thanh_toan(self):
        assert classify_intent("thanh toán 200k vé vào cửa") == Intent.LOG_EXPENSE

    def test_plain_number_k(self):
        assert classify_intent("300k đồ uống") == Intent.LOG_EXPENSE

    def test_plain_number_t(self):
        assert classify_intent("1tr ăn tối") == Intent.LOG_EXPENSE


class TestClassifyIntentTopup:
    def test_nap(self):
        assert classify_intent("nạp 500k") == Intent.LOG_TOPUP

    def test_gop(self):
        assert classify_intent("góp 1tr") == Intent.LOG_TOPUP

    def test_nap_no_advance(self):
        # "nạp" không có "để" → topup
        result = classify_intent("nạp 500k vào quỹ")
        assert result == Intent.LOG_TOPUP


class TestClassifyIntentAdvance:
    def test_ung_de_chi(self):
        assert classify_intent("ứng 1tr để chi thuê xe") == Intent.LOG_ADVANCE_EXPENSE

    def test_ung_de_tra(self):
        assert classify_intent("ứng 500k để trả tiền xăng") == Intent.LOG_ADVANCE_EXPENSE

    def test_ung_cho(self):
        assert classify_intent("ứng 200k cho nhóm") == Intent.LOG_ADVANCE_EXPENSE


class TestClassifyIntentInitialTopup:
    def test_da_nap(self):
        result = classify_intent(
            "Hà đã nạp 800k",
            trip_status=TripStatus.COLLECTING_TOPUP,
        )
        assert result == Intent.LOG_INITIAL_TOPUP

    def test_da_nap_not_collecting(self):
        # Khi trip không phải COLLECTING_TOPUP → không phải initial_topup
        result = classify_intent("Hà đã nạp 800k", trip_status=TripStatus.ACTIVE)
        assert result != Intent.LOG_INITIAL_TOPUP


class TestClassifyIntentConfirmation:
    def test_ok_confirms(self):
        result = classify_intent("ok", state=ConversationState.AWAITING_CONFIRM)
        assert result == Intent.CONFIRM

    def test_dong_y_confirms(self):
        result = classify_intent("đồng ý", state=ConversationState.AWAITING_CONFIRM)
        assert result == Intent.CONFIRM

    def test_huy_cancels(self):
        result = classify_intent("huỷ", state=ConversationState.AWAITING_CONFIRM)
        assert result == Intent.CANCEL_PENDING

    def test_sua_amends(self):
        result = classify_intent("sửa số 600k", state=ConversationState.AWAITING_CONFIRM)
        assert result == Intent.AMEND

    def test_ok_idle_not_confirm(self):
        # "ok" khi không AWAITING → không phải confirm
        result = classify_intent("ok", state=ConversationState.IDLE)
        assert result != Intent.CONFIRM


class TestClassifyIntentSpecial:
    def test_is_image(self):
        assert classify_intent("", is_image=True) == Intent.LOG_EXPENSE_IMAGE

    def test_new_user(self):
        assert classify_intent("xin chào", is_new_user=True) == Intent.WELCOME

    def test_help_natural(self):
        assert classify_intent("làm sao để ghi chi tiêu?") == Intent.HELP_OVERVIEW

    def test_unknown(self):
        assert classify_intent("hôm nay trời đẹp quá") == Intent.UNKNOWN


class TestExtractCommandArg:
    def test_trip_view(self):
        assert extract_command_arg("/trip_view TRIP-20260510", "/trip_view") == "TRIP-20260510"

    def test_empty_arg(self):
        assert extract_command_arg("/trips", "/trips") == ""

    def test_not_matching(self):
        assert extract_command_arg("/trip_view TRIP-123", "/trip_switch") == ""
