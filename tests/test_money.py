"""Tests cho app/utils/money.py"""

import pytest
from app.utils.money import (
    parse_money,
    parse_money_smart,
    parse_all_money,
    format_money,
    format_money_compact,
    is_valid_amount,
)


class TestParseMoney:
    """Test parse_money: parse số tiền VNĐ từ chuỗi."""

    # ── k (nghìn) ────────────────────────────────────────────────
    def test_k_simple(self):
        assert parse_money("500k") == 500_000

    def test_k_uppercase(self):
        assert parse_money("500K") == 500_000

    def test_k_with_prefix(self):
        assert parse_money("chi 500k mua đồ nướng") == 500_000

    def test_k_with_space(self):
        assert parse_money("chi 500 k") == 500_000

    def test_k_150(self):
        assert parse_money("taxi 150k") == 150_000

    # ── tr / triệu ───────────────────────────────────────────────
    def test_tr_simple(self):
        assert parse_money("1tr") == 1_000_000

    def test_tr_with_prefix(self):
        assert parse_money("trả 1tr tiền phòng") == 1_000_000

    def test_trieu(self):
        assert parse_money("1 triệu") == 1_000_000

    def test_tr_decimal(self):
        assert parse_money("1.5tr") == 1_500_000

    def test_tr_decimal_comma(self):
        assert parse_money("1,5tr") == 1_500_000

    def test_tr_2(self):
        assert parse_money("2tr") == 2_000_000

    # ── 1tr5 pattern (đặc biệt tiếng Việt) ─────────────────────
    def test_1tr5(self):
        assert parse_money_smart("1tr5") == 1_500_000

    def test_2tr3(self):
        assert parse_money_smart("2tr3") == 2_300_000

    def test_1tr5_in_sentence(self):
        assert parse_money_smart("trả 1tr5 tiền khách sạn") == 1_500_000

    def test_3tr7(self):
        assert parse_money_smart("3tr7") == 3_700_000

    # ── Số nguyên có dấu phân cách ───────────────────────────────
    def test_dot_separator(self):
        assert parse_money("500.000") == 500_000

    def test_comma_separator(self):
        assert parse_money("500,000") == 500_000

    def test_full_million(self):
        assert parse_money("1.000.000") == 1_000_000

    def test_with_dong_suffix(self):
        assert parse_money("500000đ") == 500_000

    def test_plain_number(self):
        assert parse_money("500000") == 500_000

    # ── Nghìn ────────────────────────────────────────────────────
    def test_nghin(self):
        assert parse_money("500 nghìn") == 500_000

    # ── None cases ───────────────────────────────────────────────
    def test_no_money(self):
        assert parse_money("hôm nay thời tiết đẹp quá") is None

    def test_empty_string(self):
        assert parse_money("") is None

    def test_text_only(self):
        assert parse_money("đi ăn thôi") is None

    # ── Multiple amounts ─────────────────────────────────────────
    def test_multiple_amounts(self):
        amounts = parse_all_money("chi 500k và 300k")
        assert 500_000 in amounts
        assert 300_000 in amounts

    def test_sentence_with_1_amount(self):
        amounts = parse_all_money("taxi 150k")
        assert amounts == [150_000]


class TestFormatMoney:
    """Test format_money và format_money_compact."""

    def test_format_500k(self):
        assert format_money(500_000) == "500.000đ"

    def test_format_1m(self):
        assert format_money(1_000_000) == "1.000.000đ"

    def test_format_1_5m(self):
        assert format_money(1_500_000) == "1.500.000đ"

    def test_compact_500k(self):
        assert format_money_compact(500_000) == "500k"

    def test_compact_1m(self):
        assert format_money_compact(1_000_000) == "1tr"

    def test_compact_1_5m(self):
        assert format_money_compact(1_500_000) == "1.5tr"

    def test_compact_2m(self):
        assert format_money_compact(2_000_000) == "2tr"


class TestIsValidAmount:
    def test_valid(self):
        assert is_valid_amount(500_000) is True

    def test_too_small(self):
        assert is_valid_amount(999) is False

    def test_too_large(self):
        assert is_valid_amount(20_000_000_000) is False

    def test_boundary_min(self):
        assert is_valid_amount(1_000) is True

    def test_boundary_max(self):
        assert is_valid_amount(10_000_000_000) is True
