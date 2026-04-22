"""
Retry policies cho mọi external call — tenacity.

Import và dùng như decorator:
    @llm_retry
    async def call_llm(...): ...

    @sheets_retry
    async def append_row(...): ...
"""

from __future__ import annotations

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
    wait_random,
    before_sleep_log,
)

log = structlog.get_logger()


class RetriableError(Exception):
    """Wrap lỗi tạm thời — tenacity sẽ retry."""
    pass


class NonRetriableError(Exception):
    """Lỗi logic (4xx) — không retry."""
    pass


NON_RETRIABLE_CODES = {400, 401, 403, 404, 422}


def classify_http_error(e: httpx.HTTPStatusError) -> Exception:
    code = e.response.status_code
    if code in NON_RETRIABLE_CODES:
        return NonRetriableError(f"HTTP {code}: {e.request.url}")
    return RetriableError(f"HTTP {code}: {e.request.url}")


# ── LLM: 3 attempts, 15s total budget ───────────────────────────────────────

_LLM_RETRY = dict(
    stop=stop_after_attempt(3) | stop_after_delay(15),
    wait=wait_exponential(multiplier=1, min=1, max=8) + wait_random(-0.3, 0.3),
    retry=retry_if_exception_type((RetriableError, httpx.TimeoutException, httpx.ConnectError)),
    before_sleep=before_sleep_log(log, "warning"),
    reraise=True,
)


def llm_retry(func):
    return retry(**_LLM_RETRY)(func)


# ── Google Sheets: 5 attempts, 45s total budget ──────────────────────────────

_SHEETS_RETRY = dict(
    stop=stop_after_attempt(5) | stop_after_delay(45),
    wait=wait_exponential(multiplier=1, min=1, max=16) + wait_random(-0.3, 0.3),
    retry=retry_if_exception_type((RetriableError, httpx.TimeoutException)),
    before_sleep=before_sleep_log(log, "warning"),
    reraise=True,
)


def sheets_retry(func):
    return retry(**_SHEETS_RETRY)(func)


# ── Google Drive: same as Sheets ─────────────────────────────────────────────

def drive_retry(func):
    return retry(**_SHEETS_RETRY)(func)


# ── Zalo send: 4 attempts, 10s total budget ──────────────────────────────────

_ZALO_RETRY = dict(
    stop=stop_after_attempt(4) | stop_after_delay(10),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4) + wait_random(-0.25, 0.25),
    retry=retry_if_exception_type((RetriableError, httpx.TimeoutException, httpx.ConnectError)),
    before_sleep=before_sleep_log(log, "warning"),
    reraise=True,
)


def zalo_retry(func):
    return retry(**_ZALO_RETRY)(func)


# ── SQLite: 3 attempts, 1s total (chỉ retry BUSY/deadlock) ───────────────────

class SqliteBusyError(Exception):
    pass


_DB_RETRY = dict(
    stop=stop_after_attempt(3) | stop_after_delay(1),
    wait=wait_exponential(multiplier=0.1, min=0.1, max=0.4) + wait_random(-0.1, 0.1),
    retry=retry_if_exception_type(SqliteBusyError),
    reraise=True,
)


def db_retry(func):
    return retry(**_DB_RETRY)(func)
