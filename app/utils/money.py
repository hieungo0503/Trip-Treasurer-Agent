"""
Utility: parse và format số tiền VNĐ tiếng Việt.

Hỗ trợ parse:
    "500k"        → 500_000
    "1tr"         → 1_000_000
    "1tr5"        → 1_500_000
    "1.5tr"       → 1_500_000
    "1 triệu"     → 1_000_000
    "500.000"     → 500_000
    "500000"      → 500_000
    "500000đ"     → 500_000
    "500,000"     → 500_000
    "500 nghìn"   → 500_000
    "2 tỷ"        → 2_000_000_000

Format output:
    500_000       → "500.000đ"
    1_500_000     → "1.500.000đ"
"""

import re
from typing import Optional

# ─── Constants ────────────────────────────────────────────────────────────────
MIN_VALID_AMOUNT = 1_000           # 1.000đ — tránh nhập nhầm
MAX_VALID_AMOUNT = 10_000_000_000  # 10 tỷ — cap hợp lý

# Regex pattern: bắt số + unit
# Thứ tự quan trọng: unit dài hơn phải đứng trước (triệu trước tr)
# Không match "1tr5" ở đây — đó là _TR5_PATTERN xử lý riêng
_AMOUNT_PATTERN = re.compile(
    r"""
    (?<!\w)                         # không đi sau chữ cái
    (?P<number>
        \d{1,3}(?:[.,]\d{3})+       # 500.000 hoặc 500,000 (có ít nhất 1 nhóm 3 số)
        |\d+[.,]\d+                  # 1.5 hoặc 1,5 (thập phân)
        |\d+                         # số nguyên đơn thuần
    )
    \s*
    (?P<unit>
        tỷ|ty|ti                    # tỷ = 1_000_000_000
        |triệu|trieu                # triệu (không nhập tr ở đây để tránh nhầm)
        |nghìn|nghin|nghiin         # nghìn = 1_000
        |tr(?!\d)                   # tr nhưng KHÔNG đi trước số (tránh nhầm 1tr5)
        |k                          # k = 1_000
        |đ|d(?!\w)                  # đồng (d chỉ khi không đi trước chữ)
    )?
    (?!\w)                          # không đi trước chữ cái
    """,
    re.VERBOSE | re.IGNORECASE,
)

_UNIT_MULTIPLIER = {
    "tỷ": 1_000_000_000,
    "ty": 1_000_000_000,
    "ti": 1_000_000_000,
    "triệu": 1_000_000,
    "trieu": 1_000_000,
    "tr": 1_000_000,
    "nghìn": 1_000,
    "nghin": 1_000,
    "nghiin": 1_000,
    "k": 1_000,
    "đ": 1,
    "d": 1,
    "": 1,  # không có unit → nguyên
}


# ─── Public API ───────────────────────────────────────────────────────────────

def parse_money(text: str) -> Optional[int]:
    """
    Parse số tiền từ chuỗi tiếng Việt.
    Trả về số nguyên VNĐ hoặc None nếu không tìm thấy / không hợp lệ.

    Ưu tiên match đầu tiên tìm được.
    Gọi parse_all_money() để lấy tất cả.

    Examples:
        >>> parse_money("chi 500k mua đồ nướng")
        500000
        >>> parse_money("1tr5 tiền khách sạn")
        1500000
        >>> parse_money("taxi 150k")
        150000
        >>> parse_money("không có số tiền")
        None
    """
    amounts = parse_all_money(text)
    return amounts[0] if amounts else None


def parse_all_money(text: str) -> list[int]:
    """
    Trả về tất cả số tiền tìm thấy trong text.
    """
    results = []
    for m in _AMOUNT_PATTERN.finditer(text):
        amount = _parse_match(m)
        if amount is not None:
            results.append(amount)
    return results


def format_money(amount: int) -> str:
    """
    Format số tiền VNĐ thành chuỗi thân thiện.

    Examples:
        >>> format_money(500000)
        '500.000đ'
        >>> format_money(1500000)
        '1.500.000đ'
    """
    # Thêm dấu chấm phân cách hàng nghìn
    formatted = f"{amount:,}".replace(",", ".")
    return f"{formatted}đ"


def format_money_compact(amount: int) -> str:
    """
    Format ngắn gọn cho display trong text ngắn.

    Examples:
        >>> format_money_compact(500000)
        '500k'
        >>> format_money_compact(1500000)
        '1.5tr'
        >>> format_money_compact(2000000)
        '2tr'
        >>> format_money_compact(1000)
        '1.000đ'
    """
    if amount >= 1_000_000:
        val = amount / 1_000_000
        if val == int(val):
            return f"{int(val)}tr"
        return f"{val:.1f}tr".rstrip("0").rstrip(".")
    if amount >= 1_000:
        val = amount / 1_000
        if val == int(val):
            return f"{int(val)}k"
    return format_money(amount)


def is_valid_amount(amount: int) -> bool:
    """Kiểm tra số tiền có nằm trong khoảng hợp lệ."""
    return MIN_VALID_AMOUNT <= amount <= MAX_VALID_AMOUNT


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _parse_match(m: re.Match) -> Optional[int]:
    """Parse 1 regex match thành số nguyên."""
    num_str = m.group("number")
    unit_str = (m.group("unit") or "").lower().strip()

    # Chuẩn hóa: xác định dấu thập phân vs phân cách nghìn
    if unit_str in ("tr", "triệu", "trieu", "k", "nghìn", "nghin", "nghiin",
                    "tỷ", "ty", "ti"):
        # Với unit nhân, dấu . hoặc , là thập phân
        # "1.5tr" → 1.5; "1,5tr" → 1.5
        # Nhưng "500.000" với unit k sẽ không xuất hiện (user sẽ gõ "500k")
        cleaned = num_str.replace(",", ".")
        # Nếu có nhiều dấu . → phân cách nghìn → bỏ hết trừ dấu cuối (nếu có)
        parts = cleaned.split(".")
        if len(parts) > 2:
            # VD: "1.500.000" với unit → bỏ dấu phân cách → 1500000
            cleaned = "".join(parts)
        try:
            num = float(cleaned)
        except ValueError:
            return None
    else:
        # Không có unit hoặc unit là đồng: số nguyên với dấu phân cách nghìn
        # "500.000" → 500000; "500,000" → 500000
        cleaned = num_str.replace(".", "").replace(",", "")
        try:
            num = float(cleaned)
        except ValueError:
            return None

    multiplier = _UNIT_MULTIPLIER.get(unit_str, 1)
    result = int(round(num * multiplier))

    if result < 0:
        return None
    return result


# ─── Special case: "1tr5" pattern ─────────────────────────────────────────────
# "1tr5" = 1.5tr = 1_500_000 — pattern đặc biệt tiếng Việt

_TR5_PATTERN = re.compile(
    r"""
    (?<!\w)
    (?P<whole>\d+)
    tr
    (?P<frac>\d+)
    (?!\w)
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _parse_tr5(text: str) -> list[tuple[int, int, int]]:
    """
    Trả về list (start, end, amount) cho pattern "Xtr Y" kiểu "1tr5", "2tr3".

    Logic:
        "1tr5"  = 1tr + 0.5tr = 1_500_000
        "2tr3"  = 2tr + 0.3tr = 2_300_000
        "1tr50" = 1tr + 0.50tr = 1_500_000
        "3tr75" = 3tr + 0.75tr = 3_750_000

    Frac được đọc như phần thập phân:
        5  → .5  → × 100_000 = 500_000
        50 → .50 → × 10_000  = 500_000
        75 → .75 → × 10_000  = 750_000
        3  → .3  → × 100_000 = 300_000
    """
    results = []
    for m in _TR5_PATTERN.finditer(text):
        whole = int(m.group("whole"))
        frac_str = m.group("frac")
        frac_int = int(frac_str)

        # Frac là phần thập phân tính theo đơn vị tr
        # "5" → 0.5 tr = 500_000; "50" → 0.50 tr = 500_000; "75" → 0.75 tr = 750_000
        # Công thức: frac_int / (10 ** len(frac_str)) * 1_000_000
        frac_vnd = int(frac_int * 1_000_000 / (10 ** len(frac_str)))

        amount = whole * 1_000_000 + frac_vnd
        results.append((m.start(), m.end(), amount))
    return results


def parse_money_smart(text: str) -> Optional[int]:
    """
    Parse thông minh: xử lý "1tr5" trước, sau mới dùng regex chung.
    Trả về None nếu không tìm thấy.
    """
    # 1. Xử lý "1tr5" style trước
    tr5_matches = _parse_tr5(text)
    if tr5_matches:
        # Lấy match đầu tiên
        return tr5_matches[0][2]

    # 2. Fallback regex chung
    return parse_money(text)
