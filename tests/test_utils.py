"""Tests cho utils: vn_time, money, retry error helpers."""

import pytest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import httpx

from app.utils.vn_time import (
    now_vn,
    now_utc,
    to_vn,
    to_utc,
    from_timestamp,
    format_vn,
    format_vn_full,
    format_date_range,
    VN_TZ,
    UTC,
)
from app.reliability.retry import (
    RetriableError,
    NonRetriableError,
    classify_http_error,
    SqliteBusyError,
)


# ── vn_time ───────────────────────────────────────────────────────────────────

class TestNowFunctions:
    def test_now_vn_is_aware(self):
        dt = now_vn()
        assert dt.tzinfo is not None
        assert dt.tzinfo.key == "Asia/Ho_Chi_Minh"

    def test_now_utc_is_aware(self):
        dt = now_utc()
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0

    def test_now_vn_and_utc_same_instant(self):
        vn = now_vn()
        utc = now_utc()
        diff = abs((vn - utc).total_seconds())
        assert diff < 5  # within 5 seconds


class TestToVn:
    def test_utc_aware_converts(self):
        utc_dt = datetime(2026, 4, 18, 12, 30, tzinfo=UTC)
        vn = to_vn(utc_dt)
        assert vn.hour == 19
        assert vn.tzinfo.key == "Asia/Ho_Chi_Minh"

    def test_naive_assumed_utc(self):
        naive = datetime(2026, 4, 18, 12, 30)
        vn = to_vn(naive)
        assert vn.hour == 19


class TestToUtc:
    def test_vn_aware_converts(self):
        vn_dt = datetime(2026, 4, 18, 19, 30, tzinfo=VN_TZ)
        utc = to_utc(vn_dt)
        assert utc.hour == 12
        assert utc.utcoffset().total_seconds() == 0

    def test_naive_stays_utc(self):
        naive = datetime(2026, 4, 18, 12, 0)
        utc = to_utc(naive)
        assert utc.hour == 12


class TestFromTimestamp:
    def test_unix_to_utc(self):
        dt = from_timestamp(0)
        assert dt.year == 1970
        assert dt.tzinfo is not None


class TestFormatVn:
    def test_format_vn_default(self):
        utc_dt = datetime(2026, 4, 18, 12, 30, tzinfo=UTC)
        result = format_vn(utc_dt)
        assert result == "18/04 19:30"

    def test_format_vn_custom_fmt(self):
        utc_dt = datetime(2026, 4, 18, 12, 30, tzinfo=UTC)
        result = format_vn(utc_dt, "%Y-%m-%d")
        assert result == "2026-04-18"

    def test_format_vn_full(self):
        utc_dt = datetime(2026, 4, 18, 12, 30, 0, tzinfo=UTC)
        result = format_vn_full(utc_dt)
        assert result == "18/04/2026 19:30:00"


class TestFormatDateRange:
    def test_same_month(self):
        start = datetime(2026, 4, 15, 0, 0, tzinfo=UTC)
        end = datetime(2026, 4, 18, 0, 0, tzinfo=UTC)
        result = format_date_range(start, end)
        assert "15" in result and "18/04" in result

    def test_same_year_diff_month(self):
        start = datetime(2026, 4, 28, 0, 0, tzinfo=UTC)
        end = datetime(2026, 5, 3, 0, 0, tzinfo=UTC)
        result = format_date_range(start, end)
        assert "→" in result

    def test_diff_year(self):
        start = datetime(2025, 12, 28, 0, 0, tzinfo=UTC)
        end = datetime(2026, 1, 3, 0, 0, tzinfo=UTC)
        result = format_date_range(start, end)
        assert "2025" in result and "2026" in result

    def test_no_end(self):
        start = datetime(2026, 4, 15, 0, 0, tzinfo=UTC)
        result = format_date_range(start, None)
        assert "2026" in result
        assert "→" not in result


# ── retry error helpers ───────────────────────────────────────────────────────

class TestClassifyHttpError:
    def _make_error(self, status_code: int) -> httpx.HTTPStatusError:
        request = httpx.Request("GET", "https://api.example.com/test")
        response = httpx.Response(status_code, request=request)
        return httpx.HTTPStatusError("error", request=request, response=response)

    def test_400_non_retriable(self):
        err = self._make_error(400)
        result = classify_http_error(err)
        assert isinstance(result, NonRetriableError)

    def test_401_non_retriable(self):
        err = self._make_error(401)
        result = classify_http_error(err)
        assert isinstance(result, NonRetriableError)

    def test_403_non_retriable(self):
        err = self._make_error(403)
        result = classify_http_error(err)
        assert isinstance(result, NonRetriableError)

    def test_404_non_retriable(self):
        err = self._make_error(404)
        result = classify_http_error(err)
        assert isinstance(result, NonRetriableError)

    def test_422_non_retriable(self):
        err = self._make_error(422)
        result = classify_http_error(err)
        assert isinstance(result, NonRetriableError)

    def test_500_retriable(self):
        err = self._make_error(500)
        result = classify_http_error(err)
        assert isinstance(result, RetriableError)

    def test_503_retriable(self):
        err = self._make_error(503)
        result = classify_http_error(err)
        assert isinstance(result, RetriableError)

    def test_429_retriable(self):
        err = self._make_error(429)
        result = classify_http_error(err)
        assert isinstance(result, RetriableError)


class TestErrorTypes:
    def test_retriable_error(self):
        err = RetriableError("timeout")
        assert str(err) == "timeout"

    def test_non_retriable_error(self):
        err = NonRetriableError("bad request")
        assert str(err) == "bad request"

    def test_sqlite_busy_error(self):
        err = SqliteBusyError("database is locked")
        assert "locked" in str(err)
