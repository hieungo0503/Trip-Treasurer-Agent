"""
Domain: logic quỹ chung (shared fund).

Nguyên tắc cốt lõi:
    - fund_balance ≥ 0 luôn luôn (invariant)
    - fund_balance tính theo input order (created_at), không phải occurred_at
    - Contribution kind advance/auto_advance KHÔNG tăng quỹ
      (chúng cancel out với expense linked)
    - Quỹ chỉ tăng với initial_topup và extra_topup
    - Quỹ chỉ giảm với expense không có linked contribution

Công thức:
    fund_balance = Σ contribution(initial_topup, extra_topup)
                 - Σ expense không có linked contribution

    contribution_i = Σ tất cả contribution của member i (mọi kind, active)
    fair_share_i   = Σ (expense.amount / len(split)) với expense có i trong split
    net_i          = contribution_i - fair_share_i

    Σ net_i = fund_balance (invariant)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.domain.models import (
    Contribution,
    ContributionKind,
    Expense,
    MemberBalance,
    FundStatus,
    Transfer,
)


# ─── Core computation ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FundSnapshot:
    """
    Snapshot tình trạng quỹ tại 1 thời điểm.
    Tất cả số liệu đều trong VNĐ.
    """
    total_topup: int        # Σ initial_topup + extra_topup
    total_advance: int      # Σ advance + auto_advance contributions
    total_expense: int      # Σ tất cả expense active
    fund_balance: int       # total_topup - (total_expense - total_advance)
    # Lưu ý: fund_balance = total_topup - Σ expense_không_linked

    def __post_init__(self) -> None:
        assert self.fund_balance >= 0, (
            f"Invariant violation: fund_balance < 0 "
            f"(topup={self.total_topup}, expense={self.total_expense}, "
            f"advance={self.total_advance})"
        )


def compute_fund_balance(
    contributions: Sequence[Contribution],
    expenses: Sequence[Expense],
) -> int:
    """
    Tính số dư quỹ hiện tại.

    Args:
        contributions: Tất cả contributions active của trip (mọi kind)
        expenses: Tất cả expenses active của trip

    Returns:
        fund_balance (int VNĐ), đảm bảo ≥ 0

    Raises:
        AssertionError: nếu invariant bị vi phạm (bug logic)
    """
    # Chỉ topup thật mới tăng quỹ
    topup_total = sum(
        c.amount_vnd
        for c in contributions
        if c.status == "active"
        and c.kind in (ContributionKind.INITIAL_TOPUP, ContributionKind.EXTRA_TOPUP)
    )

    # Expense linked với advance/auto_advance không trừ quỹ
    # (contribution đó đã "nạp" vào quỹ ảo, cancel nhau)
    # → thực tế: trừ quỹ = expense không có linked contribution
    linked_expense_ids = {
        c.linked_expense_id
        for c in contributions
        if c.status == "active"
        and c.linked_expense_id is not None
        and c.kind in (ContributionKind.ADVANCE, ContributionKind.AUTO_ADVANCE)
    }

    unlinked_expense_total = sum(
        e.amount_vnd
        for e in expenses
        if e.status == "active"
        and e.id not in linked_expense_ids
    )

    balance = topup_total - unlinked_expense_total

    assert balance >= 0, (
        f"fund_balance invariant violated: "
        f"topup={topup_total}, unlinked_expense={unlinked_expense_total}"
    )

    return balance


def compute_fund_snapshot(
    contributions: Sequence[Contribution],
    expenses: Sequence[Expense],
) -> FundSnapshot:
    """Tính FundSnapshot đầy đủ."""
    active_contribs = [c for c in contributions if c.status == "active"]
    active_expenses = [e for e in expenses if e.status == "active"]

    total_topup = sum(
        c.amount_vnd for c in active_contribs
        if c.kind in (ContributionKind.INITIAL_TOPUP, ContributionKind.EXTRA_TOPUP)
    )
    total_advance = sum(
        c.amount_vnd for c in active_contribs
        if c.kind in (ContributionKind.ADVANCE, ContributionKind.AUTO_ADVANCE)
    )
    total_expense = sum(e.amount_vnd for e in active_expenses)

    fund_balance = compute_fund_balance(active_contribs, active_expenses)

    return FundSnapshot(
        total_topup=total_topup,
        total_advance=total_advance,
        total_expense=total_expense,
        fund_balance=fund_balance,
    )


# ─── Member balance ───────────────────────────────────────────────────────────

def compute_member_balance(
    member_id: str,
    display_name: str,
    contributions: Sequence[Contribution],
    expenses: Sequence[Expense],
) -> MemberBalance:
    """
    Tính vị thế tài chính của 1 member.

    contribution_i = Σ tất cả contribution của member i (mọi kind, active)
    fair_share_i   = Σ (expense.amount / len(split)) với expense có i trong split
    net_i          = contribution_i - fair_share_i
    """
    # Contribution: tất cả kind đều tính
    contribution = sum(
        c.amount_vnd
        for c in contributions
        if c.status == "active" and c.member_id == member_id
    )

    # Fair share: từng expense, nếu member trong split_member_ids
    fair_share = 0
    for e in expenses:
        if e.status != "active":
            continue
        if member_id in e.split_member_ids:
            # Chia đều (split_method = "equal")
            n = len(e.split_member_ids)
            fair_share += e.amount_vnd // n  # integer division

    net = contribution - fair_share

    return MemberBalance(
        member_id=member_id,
        display_name=display_name,
        contribution=contribution,
        fair_share=fair_share,
        net=net,
    )


def compute_all_member_balances(
    members: list[tuple[str, str]],  # list (member_id, display_name)
    contributions: Sequence[Contribution],
    expenses: Sequence[Expense],
) -> list[MemberBalance]:
    """Tính balance cho tất cả members."""
    active_contribs = [c for c in contributions if c.status == "active"]
    active_expenses = [e for e in expenses if e.status == "active"]

    return [
        compute_member_balance(mid, name, active_contribs, active_expenses)
        for mid, name in members
    ]


# ─── Pre-transaction checks ───────────────────────────────────────────────────

@dataclass(frozen=True)
class ExpenseCheckResult:
    """Kết quả kiểm tra trước khi commit expense."""
    can_pay_from_fund: bool       # quỹ đủ không
    fund_current: int
    expense_amount: int
    deficit: int                  # 0 nếu quỹ đủ, > 0 nếu thiếu
    fund_after_if_paid: int       # sẽ bằng bao nhiêu nếu trả từ quỹ


def check_expense_against_fund(
    expense_amount: int,
    contributions: Sequence[Contribution],
    expenses: Sequence[Expense],
) -> ExpenseCheckResult:
    """
    Kiểm tra 1 expense mới có thể trả từ quỹ không.
    Dùng để quyết định có cần auto-advance không.
    """
    fund_current = compute_fund_balance(contributions, expenses)
    deficit = max(0, expense_amount - fund_current)
    fund_after = fund_current - expense_amount + (deficit if deficit > 0 else 0)

    return ExpenseCheckResult(
        can_pay_from_fund=deficit == 0,
        fund_current=fund_current,
        expense_amount=expense_amount,
        deficit=deficit,
        fund_after_if_paid=fund_current - expense_amount if deficit == 0 else 0,
    )


# ─── Invariant verification ───────────────────────────────────────────────────

@dataclass(frozen=True)
class InvariantViolation:
    name: str
    detail: str


def verify_fund_invariants(
    members: list[tuple[str, str]],
    contributions: Sequence[Contribution],
    expenses: Sequence[Expense],
) -> list[InvariantViolation]:
    """
    Kiểm tra toàn bộ invariants của fund.
    Trả về list violations (rỗng = OK).
    Gọi trong test + health check.
    """
    violations = []
    active_contribs = [c for c in contributions if c.status == "active"]
    active_expenses = [e for e in expenses if e.status == "active"]

    # 1. fund_balance >= 0
    try:
        fund = compute_fund_balance(active_contribs, active_expenses)
    except AssertionError as e:
        violations.append(InvariantViolation("fund_balance_negative", str(e)))
        return violations  # early return, không check thêm

    # 2. Σ net_i = fund_balance
    member_balances = compute_all_member_balances(members, active_contribs, active_expenses)
    sum_nets = sum(b.net for b in member_balances)
    if abs(sum_nets - fund) > 1:  # tolerance 1đ cho integer rounding
        violations.append(InvariantViolation(
            "sum_nets_not_equal_fund",
            f"Σ net_i={sum_nets} ≠ fund_balance={fund}"
        ))

    # 3. advance/auto_advance phải có linked_expense_id
    for c in active_contribs:
        if c.kind in (ContributionKind.ADVANCE, ContributionKind.AUTO_ADVANCE):
            if c.linked_expense_id is None:
                violations.append(InvariantViolation(
                    "advance_missing_link",
                    f"Contribution {c.id} kind={c.kind} has no linked_expense_id"
                ))

    # 4. initial/extra topup KHÔNG có linked_expense_id
    for c in active_contribs:
        if c.kind in (ContributionKind.INITIAL_TOPUP, ContributionKind.EXTRA_TOPUP):
            if c.linked_expense_id is not None:
                violations.append(InvariantViolation(
                    "topup_has_unexpected_link",
                    f"Contribution {c.id} kind={c.kind} should not have linked_expense_id"
                ))

    # 5. linked expense phải thuộc cùng trip
    expense_ids = {e.id for e in active_expenses}
    for c in active_contribs:
        if c.linked_expense_id and c.linked_expense_id not in expense_ids:
            violations.append(InvariantViolation(
                "linked_expense_not_found",
                f"Contribution {c.id} links to non-existent expense {c.linked_expense_id}"
            ))

    return violations
