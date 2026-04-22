"""
Domain models — Pydantic dataclasses cho toàn bộ hệ thống.
Đây là "ngôn ngữ chung" giữa các layer.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────────────

class TripStatus(str, Enum):
    DRAFT = "draft"
    COLLECTING_TOPUP = "collecting_topup"
    ACTIVE = "active"
    SETTLED = "settled"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"


class ContributionKind(str, Enum):
    INITIAL_TOPUP = "initial_topup"   # nạp đầu chuyến
    EXTRA_TOPUP = "extra_topup"       # nạp thêm bất kỳ lúc nào
    ADVANCE = "advance"               # ứng để chi trực tiếp (chủ động)
    AUTO_ADVANCE = "auto_advance"     # bot tự ghi khi quỹ không đủ


class ExpenseCategory(str, Enum):
    FOOD = "food"
    TRANSPORT = "transport"
    LODGING = "lodging"
    TICKET = "ticket"
    OTHER = "other"

    @classmethod
    def display_name(cls, cat: "ExpenseCategory") -> str:
        mapping = {
            cls.FOOD: "Ăn uống",
            cls.TRANSPORT: "Di chuyển",
            cls.LODGING: "Lưu trú",
            cls.TICKET: "Vé vào cửa",
            cls.OTHER: "Khác",
        }
        return mapping.get(cat, "Khác")

    @classmethod
    def emoji(cls, cat: "ExpenseCategory") -> str:
        mapping = {
            cls.FOOD: "🍜",
            cls.TRANSPORT: "🚗",
            cls.LODGING: "🏨",
            cls.TICKET: "🎟",
            cls.OTHER: "📦",
        }
        return mapping.get(cat, "📦")


class ExpenseSource(str, Enum):
    TEXT = "text"
    IMAGE_OCR = "image_ocr"
    API = "api"


class ConversationState(str, Enum):
    IDLE = "idle"
    AWAITING_CONFIRM = "awaiting_confirm"
    AMENDING = "amending"


class PendingKind(str, Enum):
    EXPENSE = "expense"
    CONTRIBUTION = "contribution"
    ADVANCE_EXPENSE = "advance_expense"
    INITIAL_TOPUP = "initial_topup"
    TRIP_NEW = "trip_new"
    TRIP_CONFIRM_LAUNCH = "trip_confirm_launch"


# ─── Core models ──────────────────────────────────────────────────────────────

class Member(BaseModel):
    id: str
    zalo_user_id: Optional[str] = None  # NULL cho placeholder
    display_name: str
    full_name: Optional[str] = None
    is_admin: bool = False
    active: bool = True
    created_at: datetime

    @field_validator("display_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("display_name cannot be empty")
        return v


class Trip(BaseModel):
    id: str
    name: str
    start_date: datetime
    end_date: Optional[datetime] = None
    status: TripStatus
    expected_member_count: int
    initial_topup_per_member: Optional[int] = None
    sheet_id: Optional[str] = None
    sheet_url: Optional[str] = None
    created_by: str  # member_id
    created_at: datetime
    settled_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None

    @field_validator("expected_member_count")
    @classmethod
    def count_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("expected_member_count must be >= 1")
        if v > 100:
            raise ValueError("expected_member_count must be <= 100")
        return v


class Contribution(BaseModel):
    id: str
    trip_id: str
    member_id: str
    amount_vnd: int
    kind: ContributionKind
    linked_expense_id: Optional[str] = None
    note: Optional[str] = None
    occurred_at: datetime
    created_at: datetime
    confirmed_at: datetime
    source_event_id: Optional[str] = None
    trace_id: Optional[str] = None
    status: str = "active"  # active | cancelled

    @field_validator("amount_vnd")
    @classmethod
    def amount_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount_vnd must be positive")
        return v


class Expense(BaseModel):
    id: str
    trip_id: str
    payer_id: str
    amount_vnd: int
    category: ExpenseCategory
    description: str
    split_method: str = "equal"
    split_member_ids: list[str]  # list member_id
    source: ExpenseSource
    source_raw: Optional[str] = None
    ocr_confidence: Optional[float] = None
    occurred_at: datetime
    created_at: datetime
    confirmed_at: datetime
    confirmed_by: str
    source_event_id: Optional[str] = None
    trace_id: Optional[str] = None
    status: str = "active"

    @field_validator("amount_vnd")
    @classmethod
    def amount_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount_vnd must be positive")
        return v

    @field_validator("split_member_ids")
    @classmethod
    def split_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("split_member_ids cannot be empty")
        return v


# ─── Pending confirmation ─────────────────────────────────────────────────────

class PendingExpense(BaseModel):
    """Expense đang chờ user xác nhận."""
    amount_vnd: int
    description: str
    category: ExpenseCategory
    payer_id: str
    payer_display_name: str
    split_member_ids: list[str]
    split_display_names: list[str]
    occurred_at: datetime
    source: ExpenseSource
    source_raw: Optional[str] = None
    ocr_confidence: Optional[float] = None
    # Fund info để show cho user
    fund_before: int
    fund_after: int
    # Nếu có advance đi kèm (Flow C/D)
    auto_advance_amount: Optional[int] = None  # None nếu không cần advance


class PendingContribution(BaseModel):
    """Contribution đang chờ xác nhận."""
    amount_vnd: int
    kind: ContributionKind
    member_id: str
    member_display_name: str
    note: Optional[str] = None
    occurred_at: datetime
    fund_before: int
    fund_after: int


class PendingAdvanceExpense(BaseModel):
    """Ứng tiền + chi tiêu trong 1 action (Flow D)."""
    amount_vnd: int
    description: str
    category: ExpenseCategory
    payer_id: str
    payer_display_name: str
    split_member_ids: list[str]
    split_display_names: list[str]
    occurred_at: datetime
    fund_unchanged: int  # fund không đổi (= fund_before = fund_after)


class PendingInitialTopup(BaseModel):
    """Member xác nhận nạp đầu."""
    member_id: str
    member_display_name: str
    amount_vnd: int
    expected_amount: int  # trip.initial_topup_per_member
    trip_id: str
    trip_name: str
    occurred_at: datetime
    is_partial: bool = False  # True nếu amount < expected
    is_overpaid: bool = False  # True nếu amount > expected


class PendingTripNew(BaseModel):
    """Trip đang được tạo (state DRAFT)."""
    name: str
    start_date: datetime
    end_date: Optional[datetime]
    expected_member_count: int
    initial_topup_per_member: int
    member_names: list[str]  # chờ confirm


# ─── Computed models ──────────────────────────────────────────────────────────

class MemberBalance(BaseModel):
    """Vị thế tài chính của 1 member trong trip."""
    member_id: str
    display_name: str
    contribution: int  # tổng đã góp (mọi kind)
    fair_share: int    # phần phải gánh
    net: int           # contribution - fair_share (+ được hoàn, - phải trả)


class FundStatus(BaseModel):
    """Tình trạng quỹ hiện tại của 1 trip."""
    trip_id: str
    trip_name: str
    total_topup: int        # tổng nạp (initial + extra)
    total_expense: int      # tổng chi tiêu
    fund_balance: int       # tiền còn trong quỹ (≥ 0 luôn)
    total_advances: int     # tổng đã ứng (advance + auto_advance)
    member_balances: list[MemberBalance]


class Transfer(BaseModel):
    """Giao dịch cần thực hiện để cân bằng."""
    from_member_id: str
    from_display_name: str
    to_member_id: str
    to_display_name: str
    amount_vnd: int


class SettlementResult(BaseModel):
    """Kết quả tính chia tiền."""
    trip_id: str
    fund_remain: int
    transfers: list[Transfer]
    refunds: list[Transfer]  # quỹ còn → hoàn lại mỗi người
    notes: list[str] = Field(default_factory=list)


# ─── Member resolution ────────────────────────────────────────────────────────

class MemberResolutionResult(BaseModel):
    """Kết quả resolve 1 tên khi tạo trip."""
    input_name: str
    resolved_member: Optional[Member] = None  # None nếu là member mới
    is_new: bool = False
    is_existing: bool = False
    is_ambiguous: bool = False
    ambiguous_candidates: list[Member] = Field(default_factory=list)


# ─── Parse results ────────────────────────────────────────────────────────────

class ParsedExpense(BaseModel):
    """Kết quả parse 1 tin nhắn chi tiêu."""
    amount_vnd: Optional[int] = None
    description: Optional[str] = None
    category: ExpenseCategory = ExpenseCategory.OTHER
    confidence: float = 0.0
    degraded_mode: bool = False  # True nếu dùng rule-based fallback


class ParsedTopup(BaseModel):
    amount_vnd: Optional[int] = None
    kind: ContributionKind = ContributionKind.EXTRA_TOPUP
    note: Optional[str] = None
    confidence: float = 0.0


class ParsedAdvanceExpense(BaseModel):
    amount_vnd: Optional[int] = None
    description: Optional[str] = None
    category: ExpenseCategory = ExpenseCategory.OTHER
    confidence: float = 0.0


class ParsedInitialTopup(BaseModel):
    member_name: Optional[str] = None
    amount_vnd: Optional[int] = None
    confidence: float = 0.0


class ParsedTripNew(BaseModel):
    name: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    expected_member_count: Optional[int] = None
    member_names: Optional[list[str]] = None
    amount_per_person: Optional[int] = None
    confidence: float = 0.0
    missing_fields: list[str] = Field(default_factory=list)
