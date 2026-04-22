"""Tests cho app/domain/settlement.py"""

import pytest
from app.domain.settlement import compute_settlement, format_settlement_summary
from app.domain.models import MemberBalance, SettlementResult


def make_balance(mid: str, name: str, contribution: int, fair_share: int) -> MemberBalance:
    return MemberBalance(
        member_id=mid,
        display_name=name,
        contribution=contribution,
        fair_share=fair_share,
        net=contribution - fair_share,
    )


ADMIN_ID = "M1"
ADMIN_NAME = "Đức"


class TestComputeSettlement:

    def test_all_equal_no_transfers(self):
        """
        Mọi người đóng đều nhau, chi đều nhau → net = 0 mọi người.
        Không cần transfer, chỉ hoàn quỹ còn.
        """
        balances = [
            make_balance("M1", "Đức", 1_000_000, 900_000),
            make_balance("M2", "Hà", 1_000_000, 900_000),
            make_balance("M3", "Long", 1_000_000, 900_000),
            make_balance("M4", "Minh", 1_000_000, 900_000),
        ]
        result = compute_settlement("TRIP-001", balances, fund_remain=400_000,
                                    admin_member_id=ADMIN_ID, admin_display_name=ADMIN_NAME)
        # Không ai nợ ai → không có transfer member-to-member
        assert result.transfers == []
        # Quỹ còn 400k → hoàn lại 100k/người
        total_refund = sum(r.amount_vnd for r in result.refunds)
        assert total_refund == 400_000

    def test_one_creditor_multiple_debtors(self):
        """
        Đức net +1.1tr (ứng nhiều), Hà/Long/Minh mỗi người net -200k.
        """
        balances = [
            make_balance("M1", "Đức",  2_300_000, 1_200_000),  # net = +1_100_000
            make_balance("M2", "Hà",   1_000_000, 1_200_000),  # net = -200_000
            make_balance("M3", "Long", 1_000_000, 1_200_000),  # net = -200_000
            make_balance("M4", "Minh", 1_000_000, 1_200_000),  # net = -200_000
        ]
        fund_remain = 500_000  # Σ net = 500k
        result = compute_settlement("TRIP-001", balances, fund_remain,
                                    admin_member_id=ADMIN_ID, admin_display_name=ADMIN_NAME)
        # Hà, Long, Minh mỗi người trả Đức 200k
        assert len(result.transfers) == 3
        for t in result.transfers:
            assert t.to_member_id == "M1"
            assert t.amount_vnd == 200_000

        # Quỹ còn 500k → Đức nhận thêm từ quỹ
        total_refund_to_duc = sum(
            r.amount_vnd for r in result.refunds if r.to_member_id == "M1"
        )
        assert total_refund_to_duc == 500_000

    def test_multiple_creditors_debtors(self):
        """
        A net +500k, B net +300k, C net -400k, D net -400k.
        Σ net = 0 (quỹ đã hết hoàn toàn).
        """
        balances = [
            make_balance("A", "An",   1_500_000, 1_000_000),  # +500k
            make_balance("B", "Bình", 1_300_000, 1_000_000),  # +300k
            make_balance("C", "Chi",    600_000, 1_000_000),  # -400k
            make_balance("D", "Dũng",   600_000, 1_000_000),  # -400k
        ]
        result = compute_settlement("TRIP-001", balances, fund_remain=0,
                                    admin_member_id="A", admin_display_name="An")
        # C và D phải trả cho A và B
        total_transfer = sum(t.amount_vnd for t in result.transfers)
        assert total_transfer == 800_000  # 400k + 400k

        # Không có quỹ còn → không có refunds
        assert result.refunds == []

    def test_zero_fund_zero_expense(self):
        """Chuyến không chi gì, quỹ nạp vào bao nhiêu thì hoàn lại bấy nhiêu."""
        balances = [
            make_balance("M1", "A", 1_000_000, 0),
            make_balance("M2", "B", 1_000_000, 0),
        ]
        result = compute_settlement("TRIP-001", balances, fund_remain=2_000_000,
                                    admin_member_id="M1", admin_display_name="A")
        assert result.transfers == []
        total_refund = sum(r.amount_vnd for r in result.refunds)
        assert total_refund == 2_000_000

    def test_minimum_transfers(self):
        """
        Greedy đảm bảo số giao dịch ít: N creditors, N debtors → tối đa 2N-1 transfers.
        Với 1 creditor, N debtors → N transfers.
        """
        balances = [
            make_balance("M1", "A", 5_000_000, 1_000_000),  # +4M creditor
            make_balance("M2", "B",         0, 1_000_000),  # -1M
            make_balance("M3", "C",         0, 1_000_000),  # -1M
            make_balance("M4", "D",         0, 1_000_000),  # -1M
            make_balance("M5", "E",         0, 1_000_000),  # -1M
        ]
        result = compute_settlement("TRIP-001", balances, fund_remain=0,
                                    admin_member_id="M1", admin_display_name="A")
        # 4 debtors → tối đa 4 transfers (mỗi debtor trả 1 lần)
        assert len(result.transfers) <= 4
        total = sum(t.amount_vnd for t in result.transfers)
        assert total == 4_000_000


class TestFormatSettlementSummary:
    def test_format_non_empty(self):
        balances = [
            make_balance("M1", "Đức", 2_000_000, 1_000_000),
            make_balance("M2", "Hà", 0, 1_000_000),
        ]
        result = compute_settlement("TRIP-001", balances, fund_remain=0,
                                    admin_member_id="M1", admin_display_name="Đức")
        text = format_settlement_summary(result)
        assert "CHIA TIỀN" in text
        assert "Hà" in text
        assert "Đức" in text
        assert "1.000.000đ" in text

    def test_format_no_transfers(self):
        balances = [make_balance("M1", "A", 1_000_000, 1_000_000)]
        result = compute_settlement("TRIP-001", balances, fund_remain=0,
                                    admin_member_id="M1", admin_display_name="A")
        text = format_settlement_summary(result)
        assert "Không cần chuyển khoản" in text
