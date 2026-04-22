"""
Domain: fuzzy match tên tiếng Việt.

Dùng khi user gõ "<tên> đã nạp X" và bot cần match với
danh sách display_name trong DB.

Các bước match:
    1. Exact match (sau normalize: bỏ dấu, lowercase, strip)
    2. Levenshtein distance ≤ 2
    3. Nếu không match → trả về None

Confidence score:
    1.0 = exact match
    0.8 = match sau normalize (khác dấu)
    0.6-0.7 = Levenshtein 1-2
    0.0 = không match
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MatchResult:
    matched_name: Optional[str]  # tên trong DB đã match, None nếu không match
    confidence: float            # 0.0 - 1.0
    method: str                  # "exact" | "normalized" | "levenshtein" | "none"


def normalize_vn(text: str) -> str:
    """
    Chuẩn hóa tên tiếng Việt:
    - Bỏ dấu (à á ả ã ạ → a)
    - Xử lý đ/Đ → d (ký tự này không phân rã qua NFD)
    - Lowercase
    - Strip whitespace
    - Thay ký tự đặc biệt (-, _, ...) bằng space, bỏ ký tự không phải chữ/số/space

    Examples:
        >>> normalize_vn("Hà")
        'ha'
        >>> normalize_vn("LONG ")
        'long'
        >>> normalize_vn("Đức")
        'duc'
        >>> normalize_vn("Hà-Gầy")
        'ha gay'
    """
    text = text.strip().lower()

    # Xử lý đ/Đ trước khi NFD vì chúng không phân rã thành d + combining
    text = text.replace("đ", "d").replace("Đ", "d")

    # Decompose: "à" → "a" + combining grave
    nfd = unicodedata.normalize("NFD", text)

    # Bỏ combining marks (dấu thanh, dấu mũ)
    no_accent = "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn")

    # Thay ký tự đặc biệt (-, _, ., ...) bằng space để giữ ranh giới từ
    result = "".join(ch if ch.isalnum() else " " for ch in no_accent)

    # Chuẩn hóa whitespace
    return " ".join(result.split())


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Tính Levenshtein distance giữa 2 chuỗi.
    O(n*m) DP.

    Examples:
        >>> levenshtein_distance("ha", "hà")
        0  # sau normalize
        >>> levenshtein_distance("long", "lnog")
        2
    """
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)

    m, n = len(s1), len(s2)
    # dp[i][j] = distance giữa s1[:i] và s2[:j]
    dp = list(range(n + 1))

    for i in range(1, m + 1):
        prev = dp[:]
        dp[0] = i
        for j in range(1, n + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[j] = min(
                dp[j - 1] + 1,      # insert
                prev[j] + 1,        # delete
                prev[j - 1] + cost, # replace
            )

    return dp[n]


def match_member_name(
    typed: str,
    candidates: list[str],
    max_levenshtein: int = 2,
) -> MatchResult:
    """
    Match tên user gõ với danh sách tên trong DB.

    Args:
        typed: Tên user gõ (VD: "ha", "HA", "Hã")
        candidates: Danh sách display_name từ DB (VD: ["Hà", "Long", "Minh"])
        max_levenshtein: Levenshtein tối đa để tính là match

    Returns:
        MatchResult với tên matched và confidence

    Examples:
        >>> match_member_name("ha", ["Hà", "Long"])
        MatchResult(matched_name="Hà", confidence=0.8, method="normalized")
        >>> match_member_name("Ha", ["Hà", "Long"])
        MatchResult(matched_name="Hà", confidence=0.8, method="normalized")
        >>> match_member_name("hà", ["Hà", "Long"])
        MatchResult(matched_name="Hà", confidence=1.0, method="exact")
        >>> match_member_name("xyz", ["Hà", "Long"])
        MatchResult(matched_name=None, confidence=0.0, method="none")
    """
    if not candidates:
        return MatchResult(None, 0.0, "none")

    typed_stripped = typed.strip()
    typed_norm = normalize_vn(typed_stripped)

    # Step 1: Exact match (case-insensitive)
    for c in candidates:
        if c.strip().lower() == typed_stripped.lower():
            return MatchResult(c, 1.0, "exact")

    # Step 2: Normalized match (bỏ dấu)
    for c in candidates:
        if normalize_vn(c) == typed_norm:
            return MatchResult(c, 0.8, "normalized")

    # Step 3: Levenshtein trên normalized string
    best_name: Optional[str] = None
    best_dist = max_levenshtein + 1
    best_confidence = 0.0

    for c in candidates:
        c_norm = normalize_vn(c)
        dist = levenshtein_distance(typed_norm, c_norm)
        if dist <= max_levenshtein and dist < best_dist:
            best_dist = dist
            best_name = c
            # Confidence giảm dần theo distance
            best_confidence = 0.7 if dist == 1 else 0.6

    if best_name:
        return MatchResult(best_name, best_confidence, "levenshtein")

    return MatchResult(None, 0.0, "none")


def match_all_ambiguous(
    typed: str,
    candidates: list[str],
    max_levenshtein: int = 2,
) -> list[tuple[str, float]]:
    """
    Trả về TẤT CẢ candidates có thể match, cùng confidence.
    Dùng để phát hiện ambiguous (nhiều match cùng score).

    Returns:
        List of (candidate_name, confidence), sắp xếp theo confidence giảm
    """
    typed_stripped = typed.strip()
    typed_norm = normalize_vn(typed_stripped)
    results: list[tuple[str, float]] = []

    for c in candidates:
        # Exact
        if c.strip().lower() == typed_stripped.lower():
            results.append((c, 1.0))
            continue
        # Normalized
        if normalize_vn(c) == typed_norm:
            results.append((c, 0.8))
            continue
        # Levenshtein
        dist = levenshtein_distance(typed_norm, normalize_vn(c))
        if dist <= max_levenshtein:
            conf = 0.7 if dist == 1 else 0.6
            results.append((c, conf))

    results.sort(key=lambda x: -x[1])
    return results


def capitalize_vn(name: str) -> str:
    """
    Viết hoa đầu mỗi từ theo quy tắc tiếng Việt.
    "đức nguyễn" → "Đức Nguyễn"

    Examples:
        >>> capitalize_vn("đức")
        'Đức'
        >>> capitalize_vn("hà gầy")
        'Hà Gầy'
        >>> capitalize_vn("LONG")
        'Long'
    """
    return " ".join(word.capitalize() for word in name.strip().split())
