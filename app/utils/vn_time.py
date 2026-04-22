"""
Utility: xử lý thời gian theo múi giờ Việt Nam (Asia/Ho_Chi_Minh).

Mọi timestamp hiển thị cho user đều phải qua module này.
Mọi timestamp lưu DB là UTC-aware.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
UTC = timezone.utc


def now_vn() -> datetime:
    """Trả về thời điểm hiện tại theo giờ Việt Nam (aware)."""
    return datetime.now(tz=VN_TZ)


def now_utc() -> datetime:
    """Trả về thời điểm hiện tại UTC (aware)."""
    return datetime.now(tz=UTC)


def to_vn(dt: datetime) -> datetime:
    """Chuyển datetime bất kỳ sang giờ Việt Nam."""
    if dt.tzinfo is None:
        # Naive → assume UTC
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(VN_TZ)


def to_utc(dt: datetime) -> datetime:
    """Chuyển datetime bất kỳ sang UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def from_timestamp(ts: int | float) -> datetime:
    """Chuyển Unix timestamp (Zalo webhook payload) sang datetime UTC-aware."""
    return datetime.fromtimestamp(ts, tz=UTC)


def format_vn(dt: datetime, fmt: str = "%d/%m %H:%M") -> str:
    """
    Format datetime thành chuỗi thân thiện theo giờ VN.

    Default: "18/04 19:30"

    Examples:
        >>> format_vn(datetime(2026, 4, 18, 12, 30, tzinfo=UTC))
        '18/04 19:30'
    """
    return to_vn(dt).strftime(fmt)


def format_vn_full(dt: datetime) -> str:
    """Format đầy đủ ngày giờ: "18/04/2026 19:30:00"."""
    return to_vn(dt).strftime("%d/%m/%Y %H:%M:%S")


def format_date_range(start: datetime, end: datetime | None) -> str:
    """
    Format khoảng thời gian chuyến đi thân thiện.

    Examples:
        "15/04 → 18/04"
        "15/04/2026" (nếu end=None)
    """
    start_vn = to_vn(start)
    if end is None:
        return start_vn.strftime("%d/%m/%Y")

    end_vn = to_vn(end)
    if start_vn.year == end_vn.year and start_vn.month == end_vn.month:
        return f"{start_vn.strftime('%d')}/{end_vn.strftime('%d/%m')}"
    if start_vn.year == end_vn.year:
        return f"{start_vn.strftime('%d/%m')} → {end_vn.strftime('%d/%m')}"
    return f"{start_vn.strftime('%d/%m/%Y')} → {end_vn.strftime('%d/%m/%Y')}"
