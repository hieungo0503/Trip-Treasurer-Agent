"""Tests cho app/domain/fund.py"""

import pytest
from datetime import datetime, timezone
from app.domain.fund import (
    compute_fund_balance,
    compute_fund_snapshot,
    compute_member_balance,
    compute_all_member_balances,
    check_expense_against_fund,
    verify_fund_invariants,
)
from app.domain.models import Contribution, ContributionKind, Expense, ExpenseCategory, ExpenseSource

UTC = timezone.utc
NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC)


# ─── Fixtures / Helpers ───────────────────────────────────────────────────────

def make_contribution(
    id: str,
    member_id: str,
    amount: int,
    kind: ContributionKind,
    linked_expense_id: str | None = None,
    status: str = "active",
) -> Contribution:
    return Contribution(
        id=id,
        trip_id="TRIP-001",
        member_id=member_id,
        amount_vnd=amount,
        kind=kind,
        linked_expense_id=linked_expense_id,
        occurred_at=NOW,
        created_at=NOW,
        confirmed_at=NOW,
        status=status,
    )


def make_expense(
    id: str,
    payer_id: str,
    amount: int,
    split_member_ids: list[str],
    status: str = "active",
) -> Expense:
    return Expense(
        id=id,
        trip_id="TRIP-001",
        payer_id=payer_id,
        amount_vnd=amount,
        category=ExpenseCategory.FOOD,
        description="test expense",
        split_member_ids=split_member_ids,
        source=ExpenseSource.TEXT,
        occurred_at=NOW,
        created_at=NOW,
        confirmed_at=NOW,
        confirmed_by=payer_id,
        status=status,
    )


# ─── Test compute_fund_balance ────────────────────────────────────────────────

class TestComputeFundBalance:
    """Kiểm tra tính toán số dư quỹ."""

    def test_empty(self):
        assert compute_fund_balance([], []) == 0

    def test_topup_only(self):
        """Nạp 4tr, chưa chi → quỹ = 4tr."""
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M2", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C3", "M3", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C4", "M4", 1_000_000, ContributionKind.INITIAL_TOPUP),
        ]
        assert compute_fund_balance(contribs, []) == 4_000_000

    def test_normal_expense_reduces_fund(self):
        """Nạp 4tr, chi 500k từ quỹ → còn 3.5tr."""
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M2", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C3", "M3", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C4", "M4", 1_000_000, ContributionKind.INITIAL_TOPUP),
        ]
        expenses = [make_expense("E1", "M1", 500_000, ["M1", "M2", "M3", "M4"])]
        assert compute_fund_balance(contribs, expenses) == 3_500_000

    def test_advance_does_not_reduce_fund(self):
        """
        Ứng 800k (advance) + chi 1tr → quỹ không đổi nếu advance = deficit.
        Quỹ ban đầu: 200k
        Advance 800k vào quỹ ảo, chi 1tr từ quỹ ảo → quỹ thực = 200k
        """
        contribs = [
            make_contribution("C1", "M1", 200_000, ContributionKind.INITIAL_TOPUP),
            # advance linked với E1
            make_contribution("C2", "M1", 800_000, ContributionKind.ADVANCE, linked_expense_id="E1"),
        ]
        expenses = [make_expense("E1", "M1", 1_000_000, ["M1", "M2", "M3", "M4"])]
        # E1 là linked → không trừ quỹ thực
        # advance không cộng quỹ thực
        # → quỹ thực = 200k (chỉ initial_topup)
        assert compute_fund_balance(contribs, expenses) == 200_000

    def test_auto_advance_does_not_reduce_fund(self):
        """auto_advance hoạt động giống advance."""
        contribs = [
            make_contribution("C1", "M1", 500_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M2", 500_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C3", "M1", 300_000, ContributionKind.AUTO_ADVANCE, linked_expense_id="E1"),
        ]
        expenses = [
            make_expense("E1", "M1", 800_000, ["M1", "M2"]),   # linked → không trừ quỹ
            make_expense("E2", "M2", 200_000, ["M1", "M2"]),   # không linked → trừ quỹ
        ]
        # Quỹ = 1_000_000 - 200_000 = 800_000
        assert compute_fund_balance(contribs, expenses) == 800_000

    def test_extra_topup_increases_fund(self):
        """Nạp thêm giữa chuyến tăng quỹ."""
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M1", 500_000, ContributionKind.EXTRA_TOPUP),
        ]
        assert compute_fund_balance(contribs, []) == 1_500_000

    def test_cancelled_contribution_not_counted(self):
        """Contribution bị huỷ không tính vào quỹ."""
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M1", 500_000, ContributionKind.INITIAL_TOPUP, status="cancelled"),
        ]
        assert compute_fund_balance(contribs, []) == 1_000_000

    def test_cancelled_expense_not_counted(self):
        """Expense bị huỷ không trừ quỹ."""
        contribs = [
            make_contribution("C1", "M1", 2_000_000, ContributionKind.INITIAL_TOPUP),
        ]
        expenses = [
            make_expense("E1", "M1", 500_000, ["M1"], status="active"),
            make_expense("E2", "M1", 300_000, ["M1"], status="cancelled"),
        ]
        assert compute_fund_balance(contribs, expenses) == 1_500_000


# ─── Test compute_member_balance ─────────────────────────────────────────────

class TestComputeMemberBalance:
    """Kiểm tra vị thế tài chính của mỗi member."""

    def test_all_equal_no_advance(self):
        """4 người nạp 1tr, chi tổng 3.2tr → fair_share 800k/người."""
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M2", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C3", "M3", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C4", "M4", 1_000_000, ContributionKind.INITIAL_TOPUP),
        ]
        expenses = [
            make_expense("E1", "M1", 800_000, ["M1", "M2", "M3", "M4"]),
            make_expense("E2", "M2", 800_000, ["M1", "M2", "M3", "M4"]),
            make_expense("E3", "M3", 800_000, ["M1", "M2", "M3", "M4"]),
            make_expense("E4", "M4", 800_000, ["M1", "M2", "M3", "M4"]),
        ]
        b = compute_member_balance("M1", "Đức", contribs, expenses)
        assert b.contribution == 1_000_000
        assert b.fair_share == 800_000  # 3.2tr / 4
        assert b.net == 200_000         # dư 200k

    def test_advance_increases_contribution(self):
        """Advance tính vào contribution của member."""
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M1", 800_000, ContributionKind.ADVANCE, linked_expense_id="E1"),
        ]
        b = compute_member_balance("M1", "Đức", contribs, [])
        # Cả initial_topup lẫn advance đều tính vào contribution
        assert b.contribution == 1_800_000

    def test_net_sum_equals_fund(self):
        """Σ net = fund_balance (invariant kiểm tra bằng tay)."""
        members = [("M1", "A"), ("M2", "B"), ("M3", "C"), ("M4", "D")]
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M2", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C3", "M3", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C4", "M4", 1_000_000, ContributionKind.INITIAL_TOPUP),
        ]
        expenses = [make_expense("E1", "M1", 500_000, ["M1", "M2", "M3", "M4"])]

        balances = compute_all_member_balances(members, contribs, expenses)
        sum_nets = sum(b.net for b in balances)
        fund = compute_fund_balance(contribs, expenses)

        assert abs(sum_nets - fund) <= 1  # tolerance 1đ rounding


# ─── Test check_expense_against_fund ─────────────────────────────────────────

class TestCheckExpenseAgainstFund:
    def test_fund_sufficient(self):
        contribs = [make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP)]
        result = check_expense_against_fund(500_000, contribs, [])
        assert result.can_pay_from_fund is True
        assert result.deficit == 0
        assert result.fund_after_if_paid == 500_000

    def test_fund_insufficient(self):
        contribs = [make_contribution("C1", "M1", 200_000, ContributionKind.INITIAL_TOPUP)]
        result = check_expense_against_fund(1_000_000, contribs, [])
        assert result.can_pay_from_fund is False
        assert result.deficit == 800_000
        assert result.fund_current == 200_000

    def test_fund_exactly_enough(self):
        contribs = [make_contribution("C1", "M1", 500_000, ContributionKind.INITIAL_TOPUP)]
        result = check_expense_against_fund(500_000, contribs, [])
        assert result.can_pay_from_fund is True
        assert result.fund_after_if_paid == 0


# ─── Test verify_fund_invariants ─────────────────────────────────────────────

class TestVerifyFundInvariants:
    def test_no_violations_happy_path(self):
        members = [("M1", "A"), ("M2", "B")]
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M2", 1_000_000, ContributionKind.INITIAL_TOPUP),
        ]
        expenses = [make_expense("E1", "M1", 500_000, ["M1", "M2"])]
        violations = verify_fund_invariants(members, contribs, expenses)
        assert violations == []

    def test_advance_without_link_is_violation(self):
        members = [("M1", "A")]
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M1", 500_000, ContributionKind.ADVANCE),  # No link!
        ]
        violations = verify_fund_invariants(members, contribs, [])
        names = [v.name for v in violations]
        assert "advance_missing_link" in names

    def test_topup_with_link_is_violation(self):
        members = [("M1", "A")]
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP, linked_expense_id="E1"),
        ]
        violations = verify_fund_invariants(members, contribs, [])
        names = [v.name for v in violations]
        assert "topup_has_unexpected_link" in names

    def test_linked_expense_not_found(self):
        members = [("M1", "A")]
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M1", 500_000, ContributionKind.ADVANCE, linked_expense_id="E999"),
        ]
        expenses = []  # E999 không tồn tại
        violations = verify_fund_invariants(members, contribs, expenses)
        names = [v.name for v in violations]
        assert "linked_expense_not_found" in names


# ─── Integration scenario tests ──────────────────────────────────────────────

class TestFundScenarios:
    """Test các kịch bản thực tế end-to-end trong domain."""

    def test_scenario_normal_trip(self):
        """
        4 người nạp 1tr, chi tổng 3.6tr → quỹ còn 400k.
        Fair share = 900k/người.
        Mỗi người net = +100k.
        """
        members = [("M1", "Đức"), ("M2", "Hà"), ("M3", "Long"), ("M4", "Minh")]
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M2", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C3", "M3", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C4", "M4", 1_000_000, ContributionKind.INITIAL_TOPUP),
        ]
        all_members = ["M1", "M2", "M3", "M4"]
        expenses = [
            make_expense("E1", "M1", 500_000, all_members),
            make_expense("E2", "M2", 400_000, all_members),
            make_expense("E3", "M1", 600_000, all_members),
            make_expense("E4", "M3", 500_000, all_members),
            make_expense("E5", "M4", 800_000, all_members),
            make_expense("E6", "M2", 800_000, all_members),
        ]  # Total: 3_600_000

        fund = compute_fund_balance(contribs, expenses)
        assert fund == 400_000

        balances = compute_all_member_balances(members, contribs, expenses)
        for b in balances:
            assert b.fair_share == 900_000
            assert b.net == 100_000

        violations = verify_fund_invariants(members, contribs, expenses)
        assert violations == []

    def test_scenario_advance_in_trip(self):
        """
        Đức ứng 1.3tr để chi thuê thuyền → quỹ không đổi.
        Đức có contribution_total = 1tr + 1.3tr = 2.3tr.
        """
        members = [("M1", "Đức"), ("M2", "Hà"), ("M3", "Long"), ("M4", "Minh")]
        contribs = [
            make_contribution("C1", "M1", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C2", "M2", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C3", "M3", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C4", "M4", 1_000_000, ContributionKind.INITIAL_TOPUP),
            make_contribution("C5", "M1", 1_300_000, ContributionKind.ADVANCE, linked_expense_id="E5"),
        ]
        all_members = ["M1", "M2", "M3", "M4"]
        expenses = [
            make_expense("E1", "M1", 500_000, all_members),
            make_expense("E2", "M2", 800_000, all_members),
            make_expense("E3", "M3", 800_000, all_members),
            make_expense("E4", "M4", 800_000, all_members),
            make_expense("E5", "M1", 1_300_000, all_members),  # linked advance
        ]  # Unlinked total = 500+800+800+800 = 2_900_000

        fund = compute_fund_balance(contribs, expenses)
        assert fund == 1_100_000  # 4_000_000 - 2_900_000

        balances = compute_all_member_balances(members, contribs, expenses)

        # Tổng chi = 4_200_000, fair = 1_050_000/người
        duc_b = next(b for b in balances if b.member_id == "M1")
        assert duc_b.contribution == 2_300_000  # 1tr + 1.3tr advance
        assert duc_b.fair_share == 1_050_000
        assert duc_b.net == 1_250_000  # được nhận

        # Σ net = fund_balance
        sum_nets = sum(b.net for b in balances)
        assert abs(sum_nets - fund) <= 4  # tolerance 4đ cho integer division

        violations = verify_fund_invariants(members, contribs, expenses)
        assert violations == []
