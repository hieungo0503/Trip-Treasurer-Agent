"""
Retry configurations cho từng external service.
Copy module này vào app/reliability/retry.py
"""

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
    """Lỗi tạm thời, nên retry."""
    pass


class NonRetriableError(Exception):
    """Lỗi logic, KHÔNG retry."""
    pass


# HTTP status codes nào là retriable
RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}
NON_RETRIABLE_STATUS_CODES = {400, 401, 403, 404, 422}


def classify_http_error(e: httpx.HTTPStatusError) -> Exception:
    """Phân loại HTTP error thành retriable hay không."""
    code = e.response.status_code
    if code in RETRIABLE_STATUS_CODES:
        return RetriableError(f"HTTP {code}: {e}")
    return NonRetriableError(f"HTTP {code}: {e}")


# ─── LLM (Viettel Netmind) ────────────────────────────────────────────────────

_LLM_RETRY = dict(
    stop=stop_after_attempt(3) | stop_after_delay(15),
    wait=wait_exponential(multiplier=1, min=1, max=8) + wait_random(-0.3, 0.3),
    retry=retry_if_exception_type((RetriableError, httpx.TimeoutException, httpx.ConnectError)),
    before_sleep=before_sleep_log(log, "warning"),
    reraise=True,
)


def llm_retry(func):
    """Decorator: retry LLM call với exponential backoff."""
    return retry(**_LLM_RETRY)(func)


# ─── Google Sheets ────────────────────────────────────────────────────────────

_SHEETS_RETRY = dict(
    stop=stop_after_attempt(5) | stop_after_delay(45),
    wait=wait_exponential(multiplier=1, min=1, max=16) + wait_random(-0.3, 0.3),
    retry=retry_if_exception_type((RetriableError, httpx.TimeoutException)),
    before_sleep=before_sleep_log(log, "warning"),
    reraise=True,
)


def sheets_retry(func):
    return retry(**_SHEETS_RETRY)(func)


# ─── Google Drive ─────────────────────────────────────────────────────────────

_DRIVE_RETRY = dict(
    stop=stop_after_attempt(5) | stop_after_delay(45),
    wait=wait_exponential(multiplier=1, min=1, max=16) + wait_random(-0.3, 0.3),
    retry=retry_if_exception_type((RetriableError, httpx.TimeoutException)),
    before_sleep=before_sleep_log(log, "warning"),
    reraise=True,
)


def drive_retry(func):
    return retry(**_DRIVE_RETRY)(func)


# ─── Zalo Send ────────────────────────────────────────────────────────────────

_ZALO_RETRY = dict(
    stop=stop_after_attempt(4) | stop_after_delay(10),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=4) + wait_random(-0.25, 0.25),
    retry=retry_if_exception_type((RetriableError, httpx.TimeoutException)),
    before_sleep=before_sleep_log(log, "warning"),
    reraise=True,
)


def zalo_retry(func):
    return retry(**_ZALO_RETRY)(func)


# ─── Helper: wrap Google API exception ────────────────────────────────────────

def handle_google_api_error(e: Exception) -> None:
    """
    Google API client raise googleapiclient.errors.HttpError.
    Convert sang RetriableError hoặc NonRetriableError.
    """
    from googleapiclient.errors import HttpError
    if isinstance(e, HttpError):
        code = e.resp.status
        if code in RETRIABLE_STATUS_CODES:
            raise RetriableError(f"Google API {code}") from e
        raise NonRetriableError(f"Google API {code}") from e
    raise


# ─── Usage examples ───────────────────────────────────────────────────────────

"""
# LLM call
from app.reliability.retry import llm_retry, RetriableError, classify_http_error
import httpx

@llm_retry
async def call_llm(prompt: str, ctx) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(
                f"{LLM_BASE_URL}/v1/chat/completions",
                json={"model": MODEL, "messages": [...]},
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise classify_http_error(e) from e
        return resp.json()


# Sheets call
from app.reliability.retry import sheets_retry, handle_google_api_error

@sheets_retry
async def append_row(sheet_id: str, row: list, sheets_client):
    try:
        sheets_client.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="Chi tiêu!A:Z",
            valueInputOption="RAW",
            body={"values": [row]},
        ).execute()
    except Exception as e:
        handle_google_api_error(e)
"""
