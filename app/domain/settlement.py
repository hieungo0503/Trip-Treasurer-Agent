"""
Domain: thuật toán settlement (chia tiền cuối chuyến).

Bài toán:
    Cho N người với net_i (+ được nhận, − phải trả),
    tìm cách transfer tiền với số giao dịch ít nhất.

Thuật toán: Greedy (không đảm bảo tối ưu tuyệt đối — NP-hard,
nhưng với N ≤ 20 người thì kết quả rất gần tối ưu).

Ví dụ:
    A: net = +1.100.000 (được nhận)
    B: net = -200.000   (phải trả)
    C: net = -200.000
    D: net = -200.000

    Quỹ còn 500.000 (admin Đức giữ):
    → B → A: 200k, C → A: 200k, D → A: 200k  (3 giao dịch)
    → Quỹ 500k → A: 500k (1 giao dịch từ admin)
    Tổng: 4 giao dịch
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from app.domain.models import (
    MemberBalance,
    SettlementResult,
    Transfer,
)

ROUNDING_TOLERANCE = 10  # đồng, bỏ qua số lẻ nhỏ hơn thế này


def compute_settlement(
    trip_id: str,
    member_balances: list[MemberBalance],
    fund_remain: int,
    admin_member_id: str,
    admin_display_name: str,
) -> SettlementResult:
    """
    Tính toán chia tiền cuối chuyến.

    Args:
        trip_id: ID của trip
        member_balances: Danh sách MemberBalance (contribution, fair_share, net)
        fund_remain: Số tiền còn lại trong quỹ (≥ 0)
        admin_member_id: Người giữ tiền quỹ (thường là người tạo trip)
        admin_display_name: Tên hiển thị của admin

    Returns:
        SettlementResult với danh sách Transfer tối thiểu

    Logic:
        1. Tìm creditors (net > 0 → được nhận) và debtors (net < 0 → phải trả)
        2. Greedy: debtors trả cho creditors cho đến khi cân bằng
        3. Xử lý quỹ còn: admin chia lại quỹ cho creditors
    """
    notes: list[str] = []

    # Kiểm tra sanity: Σ net = fund_remain
    sum_nets = sum(b.net for b in member_balances)
    if abs(sum_nets - fund_remain) > ROUNDING_TOLERANCE:
        notes.append(
            f"⚠️ Cảnh báo: Σ net ({sum_nets:,}đ) ≠ quỹ còn ({fund_remain:,}đ). "
            "Có thể có lỗi dữ liệu."
        )

    # Tách creditors (net > 0) và debtors (net < 0)
    creditors: list[tuple[str, str, int]] = []  # (member_id, name, amount)
    debtors: list[tuple[str, str, int]] = []

    for b in member_balances:
        if b.net > ROUNDING_TOLERANCE:
            creditors.append((b.member_id, b.display_name, b.net))
        elif b.net < -ROUNDING_TOLERANCE:
            debtors.append((b.member_id, b.display_name, -b.net))

    # Sắp xếp giảm dần để greedy hiệu quả hơn
    creditors.sort(key=lambda x: -x[2])
    debtors.sort(key=lambda x: -x[2])

    # Greedy settlement
    transfers = _greedy_settle(debtors, creditors)

    # Phân phối quỹ còn (admin → creditors)
    refunds: list[Transfer] = []
    if fund_remain > ROUNDING_TOLERANCE:
        refunds = _distribute_fund_remain(
            fund_remain=fund_remain,
            admin_member_id=admin_member_id,
            admin_display_name=admin_display_name,
            member_balances=member_balances,
        )
        notes.append(
            f"Quỹ còn {fund_remain:,}đ do admin ({admin_display_name}) giữ, "
            "sẽ được chuyển lại theo bảng 'Hoàn quỹ' dưới."
        )

    return SettlementResult(
        trip_id=trip_id,
        fund_remain=fund_remain,
        transfers=transfers,
        refunds=refunds,
        notes=notes,
    )


def _greedy_settle(
    debtors: list[tuple[str, str, int]],
    creditors: list[tuple[str, str, int]],
) -> list[Transfer]:
    """
    Greedy settlement: tối thiểu hóa số giao dịch giữa các member.

    Cả debtors và creditors là mutable list (bị modify trong quá trình).
    """
    transfers: list[Transfer] = []

    # Work on copies để không mutate input
    debtors_work = [[mid, name, amt] for mid, name, amt in debtors]
    creditors_work = [[mid, name, amt] for mid, name, amt in creditors]

    i, j = 0, 0
    while i < len(debtors_work) and j < len(creditors_work):
        debtor_id, debtor_name, debt = debtors_work[i]
        creditor_id, creditor_name, credit = creditors_work[j]

        amount = min(debt, credit)

        if amount > ROUNDING_TOLERANCE:
            transfers.append(Transfer(
                from_member_id=debtor_id,
                from_display_name=debtor_name,
                to_member_id=creditor_id,
                to_display_name=creditor_name,
                amount_vnd=_round_vnd(amount),
            ))

        debtors_work[i][2] -= amount
        creditors_work[j][2] -= amount

        if debtors_work[i][2] <= ROUNDING_TOLERANCE:
            i += 1
        if creditors_work[j][2] <= ROUNDING_TOLERANCE:
            j += 1

    return transfers


def _distribute_fund_remain(
    fund_remain: int,
    admin_member_id: str,
    admin_display_name: str,
    member_balances: list[MemberBalance],
) -> list[Transfer]:
    """
    Phân phối quỹ còn cho các creditors (người có net > 0).

    Nếu tất cả net = 0 (không ai có dư) → chia đều cho mọi người.
    """
    refunds: list[Transfer] = []

    creditors = [b for b in member_balances if b.net > ROUNDING_TOLERANCE]

    if not creditors:
        # Không có ai có net > 0 → chia đều
        n = len(member_balances)
        per_person = fund_remain // n
        remainder = fund_remain - per_person * n

        for idx, b in enumerate(member_balances):
            amount = per_person + (remainder if idx == 0 else 0)
            if amount > ROUNDING_TOLERANCE:
                refunds.append(Transfer(
                    from_member_id=admin_member_id,
                    from_display_name=admin_display_name,
                    to_member_id=b.member_id,
                    to_display_name=b.display_name,
                    amount_vnd=amount,
                ))
        return refunds

    # Có creditors → họ được nhận tiền từ quỹ còn
    # Mỗi creditor nhận min(net, phần quỹ còn tương ứng)
    total_credit = sum(b.net for b in creditors)

    for b in creditors:
        if total_credit == 0:
            share = fund_remain // len(creditors)
        else:
            share = int(fund_remain * b.net / total_credit)

        if share > ROUNDING_TOLERANCE:
            refunds.append(Transfer(
                from_member_id=admin_member_id,
                from_display_name=admin_display_name,
                to_member_id=b.member_id,
                to_display_name=b.display_name,
                amount_vnd=share,
            ))

    return refunds


def _round_vnd(amount: float) -> int:
    """Round về bội số của 1.000 (tránh số lẻ khó chuyển khoản)."""
    return int(round(amount / 1000) * 1000)


# ─── Display helpers ──────────────────────────────────────────────────────────

def format_settlement_summary(result: SettlementResult) -> str:
    """
    Format SettlementResult thành text thân thiện gửi qua Zalo.
    """
    lines: list[str] = []

    if result.transfers:
        lines.append("💸 CHIA TIỀN:")
        for t in result.transfers:
            lines.append(
                f"  {t.from_display_name} → {t.to_display_name}: "
                f"{t.amount_vnd:,}đ".replace(",", ".")
            )
    else:
        lines.append("✅ Không cần chuyển khoản giữa các thành viên!")

    if result.refunds:
        lines.append("")
        lines.append("💰 HOÀN QUỸ (admin chuyển lại):")
        for r in result.refunds:
            lines.append(
                f"  {r.from_display_name} → {r.to_display_name}: "
                f"{r.amount_vnd:,}đ".replace(",", ".")
            )

    if result.notes:
        lines.append("")
        for note in result.notes:
            lines.append(f"ℹ️ {note}")

    n_transfers = len(result.transfers) + len(result.refunds)
    lines.append(f"\n(Tổng: {n_transfers} giao dịch)")

    return "\n".join(lines)
