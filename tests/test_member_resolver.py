"""Tests cho app/domain/member_resolver.py"""

import pytest
from datetime import datetime, timezone
from app.domain.member_resolver import (
    resolve_members_sync,
    DuplicateNameInTripError,
    TripMemberPlan,
)
from app.domain.models import Member

UTC = timezone.utc
NOW = datetime(2026, 4, 18, tzinfo=UTC)


def make_member(id: str, name: str, zalo_id: str | None = "zalo_" + "x") -> Member:
    return Member(
        id=id,
        zalo_user_id=zalo_id,
        display_name=name,
        active=True,
        created_at=NOW,
    )


class TestResolveMembersSync:

    def test_all_new_members(self):
        """Không có member nào trong DB → tất cả là mới."""
        plan = resolve_members_sync(["Đức", "Hà", "Long", "Minh"], [])
        assert plan.has_new is True
        assert len(plan.new_placeholder_names) == 4
        assert plan.has_ambiguous is False

    def test_all_existing_members(self):
        """Tất cả đã có trong DB."""
        existing = [
            make_member("M1", "Đức"),
            make_member("M2", "Hà"),
            make_member("M3", "Long"),
            make_member("M4", "Minh"),
        ]
        plan = resolve_members_sync(["Đức", "Hà", "Long", "Minh"], existing)
        assert plan.has_new is False
        assert plan.has_ambiguous is False
        assert len(plan.existing_members) == 4

    def test_mixed_new_and_existing(self):
        """Một số member cũ, một số mới."""
        existing = [
            make_member("M1", "Đức"),
            make_member("M2", "Hà"),
        ]
        plan = resolve_members_sync(["Đức", "Hà", "An", "Bình"], existing)
        assert len(plan.existing_members) == 2
        assert len(plan.new_placeholder_names) == 2
        assert "An" in plan.new_placeholder_names
        assert "Bình" in plan.new_placeholder_names

    def test_duplicate_name_raises(self):
        """2 tên giống nhau trong danh sách → DuplicateNameInTripError."""
        with pytest.raises(DuplicateNameInTripError):
            resolve_members_sync(["Đức", "Hà", "Hà", "Minh"], [])

    def test_duplicate_case_insensitive(self):
        """'ha' và 'Hà' là duplicate."""
        with pytest.raises(DuplicateNameInTripError):
            resolve_members_sync(["Đức", "ha", "Hà", "Minh"], [])

    def test_ambiguous_name_two_ha(self):
        """Có 2 người tên Hà trong DB → ambiguous."""
        existing = [
            make_member("M1", "Đức"),
            make_member("M2", "Hà", zalo_id="zalo1"),
            make_member("M3", "Hà", zalo_id="zalo2"),
        ]
        plan = resolve_members_sync(["Đức", "Hà", "Long"], existing)
        assert plan.has_ambiguous is True
        ambiguous = [r for r in plan.resolutions if r.is_ambiguous]
        assert len(ambiguous) == 1
        assert len(ambiguous[0].ambiguous_candidates) == 2

    def test_capitalize_name(self):
        """Tên viết thường được capitalize."""
        plan = resolve_members_sync(["đức", "hà"], [])
        names = [r.input_name for r in plan.resolutions]
        assert "Đức" in names
        assert "Hà" in names

    def test_existing_with_zalo(self):
        """Members đã có zalo_user_id → bot có thể ping trực tiếp."""
        existing = [
            make_member("M1", "Đức", zalo_id="zalo_duc"),
            make_member("M2", "Hà", zalo_id=None),  # placeholder, chưa link
        ]
        plan = resolve_members_sync(["Đức", "Hà"], existing)
        assert len(plan.existing_with_zalo) == 1
        assert plan.existing_with_zalo[0].display_name == "Đức"

    def test_inactive_member_not_matched(self):
        """Member đã inactive không được reuse."""
        existing = [
            Member(id="M1", display_name="Đức", active=False, created_at=NOW)
        ]
        plan = resolve_members_sync(["Đức"], existing)
        # active=False → không match → tạo mới
        assert plan.has_new is True
        assert len(plan.new_placeholder_names) == 1
