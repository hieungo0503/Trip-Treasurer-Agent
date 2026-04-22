"""
Domain: resolve member khi tạo trip mới.

Logic:
    1. Với mỗi tên admin khai → search DB
    2. 0 match → tạo placeholder (member mới)
    3. 1 match → reuse member cũ
    4. 2+ match → ambiguous, cần admin chọn

Tên phải unique trong trip (enforce ở đây).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

from app.domain.fuzzy_match import normalize_vn, capitalize_vn
from app.domain.models import Member, MemberResolutionResult


# ─── Exceptions ───────────────────────────────────────────────────────────────

class DuplicateNameInTripError(Exception):
    """2 thành viên trong cùng 1 trip có tên giống nhau."""
    def __init__(self, name: str):
        super().__init__(f"Duplicate name in trip: '{name}'")
        self.name = name


class AmbiguousNameError(Exception):
    """Tên match với 2+ member trong DB."""
    def __init__(self, name: str, candidates: list[Member]):
        super().__init__(
            f"Ambiguous name '{name}': {len(candidates)} candidates found"
        )
        self.name = name
        self.candidates = candidates


# ─── Resolution ───────────────────────────────────────────────────────────────

@dataclass
class TripMemberPlan:
    """
    Kết quả resolve toàn bộ danh sách member cho 1 trip mới.
    """
    resolutions: list[MemberResolutionResult]
    has_ambiguous: bool = field(init=False)
    has_new: bool = field(init=False)

    def __post_init__(self):
        self.has_ambiguous = any(r.is_ambiguous for r in self.resolutions)
        self.has_new = any(r.is_new for r in self.resolutions)

    @property
    def existing_members(self) -> list[Member]:
        return [
            r.resolved_member
            for r in self.resolutions
            if r.is_existing and r.resolved_member is not None
        ]

    @property
    def existing_with_zalo(self) -> list[Member]:
        """Members cũ đã có zalo_user_id → có thể ping trực tiếp."""
        return [m for m in self.existing_members if m.zalo_user_id is not None]

    @property
    def new_placeholder_names(self) -> list[str]:
        """Tên cần tạo placeholder mới."""
        return [r.input_name for r in self.resolutions if r.is_new]


# SearchMemberFn: callable async tìm member theo tên
# Inject từ storage layer để domain không phụ thuộc DB
SearchMemberFn = Callable[[str], Awaitable[list[Member]]]


async def resolve_members_for_trip(
    names: list[str],
    search_by_name: SearchMemberFn,
) -> TripMemberPlan:
    """
    Resolve danh sách tên admin khai → TripMemberPlan.

    Args:
        names: Danh sách tên (raw, từ admin input, có thể viết thường/hoa tùy)
        search_by_name: Async function tìm member theo display_name

    Returns:
        TripMemberPlan với đầy đủ resolution

    Raises:
        DuplicateNameInTripError: nếu có 2 tên giống nhau trong list
    """
    # Normalize để check duplicate (case/dấu insensitive)
    seen_norms: set[str] = set()
    resolutions: list[MemberResolutionResult] = []

    for raw_name in names:
        clean_name = capitalize_vn(raw_name)
        norm = normalize_vn(clean_name)

        # Check duplicate trong current list
        if norm in seen_norms:
            raise DuplicateNameInTripError(clean_name)
        seen_norms.add(norm)

        # Search DB
        matches = await search_by_name(clean_name)

        if len(matches) == 0:
            resolutions.append(MemberResolutionResult(
                input_name=clean_name,
                resolved_member=None,
                is_new=True,
                is_existing=False,
                is_ambiguous=False,
            ))

        elif len(matches) == 1:
            resolutions.append(MemberResolutionResult(
                input_name=clean_name,
                resolved_member=matches[0],
                is_new=False,
                is_existing=True,
                is_ambiguous=False,
            ))

        else:
            # 2+ matches → ambiguous
            resolutions.append(MemberResolutionResult(
                input_name=clean_name,
                resolved_member=None,
                is_new=False,
                is_existing=False,
                is_ambiguous=True,
                ambiguous_candidates=matches,
            ))

    return TripMemberPlan(resolutions=resolutions)


def resolve_members_sync(
    names: list[str],
    existing_members: list[Member],
) -> TripMemberPlan:
    """
    Phiên bản sync của resolve_members_for_trip, dùng cho test.

    Args:
        names: Danh sách tên cần resolve
        existing_members: Danh sách tất cả members trong "DB" (mock)
    """
    seen_norms: set[str] = set()
    resolutions: list[MemberResolutionResult] = []

    for raw_name in names:
        clean_name = capitalize_vn(raw_name)
        norm = normalize_vn(clean_name)

        if norm in seen_norms:
            raise DuplicateNameInTripError(clean_name)
        seen_norms.add(norm)

        # Simple name match (normalize)
        matches = [
            m for m in existing_members
            if normalize_vn(m.display_name) == norm and m.active
        ]

        if len(matches) == 0:
            resolutions.append(MemberResolutionResult(
                input_name=clean_name,
                is_new=True,
            ))
        elif len(matches) == 1:
            resolutions.append(MemberResolutionResult(
                input_name=clean_name,
                resolved_member=matches[0],
                is_existing=True,
            ))
        else:
            resolutions.append(MemberResolutionResult(
                input_name=clean_name,
                is_ambiguous=True,
                ambiguous_candidates=matches,
            ))

    return TripMemberPlan(resolutions=resolutions)


def format_ambiguous_card(name: str, candidates: list[Member]) -> str:
    """
    Format card hỏi admin khi có ambiguous name.
    """
    lines = [
        f"⚠️ Có {len(candidates)} người tên \"{name}\" trong hệ thống:",
        "",
    ]

    for idx, m in enumerate(candidates, 1):
        zalo_info = "đã link Zalo" if m.zalo_user_id else "chưa link Zalo"
        lines.append(f"   {idx}. {m.display_name} (ID: {m.id}, {zalo_info})")

    lines += [
        "",
        f"Bạn chọn ai?",
        f"   Gõ số (1-{len(candidates)}) để chọn",
        f'   Hoặc gõ "mới" để tạo người mới',
        f'   (Nếu tạo mới, đặt tên phân biệt: VD "Hà béo", "Hà gầy")',
    ]

    return "\n".join(lines)
