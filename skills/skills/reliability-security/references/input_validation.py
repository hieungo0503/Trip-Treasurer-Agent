"""
Input Validation — 4 tầng filter.
Copy module này vào app/security/input_validation.py
"""

import re
import unicodedata
from typing import Optional

import structlog

log = structlog.get_logger()

# ─── Constants ────────────────────────────────────────────────────────────────

MAX_INPUT_LENGTH = 500
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

ZERO_WIDTH_CHARS = ['\u200b', '\u200c', '\u200d', '\ufeff']

INJECTION_REGEX = re.compile(
    r'ignore\s+(previous|prior|above|all)\s+(instruction|prompt)'
    r'|disregard\s+(previous|prior)'
    r'|forget\s+(everything|previous|prior)'
    r'|you\s+are\s+now\s+'
    r'|from\s+now\s+on\s+you'
    r'|act\s+as\s+(a\s+)?(different|admin|system|new)'
    r'|what\s+(is|are)\s+your\s+(instruction|prompt|system)'
    r'|repeat\s+(the|your)\s+(instruction|prompt|system)'
    r'|bỏ\s+qua\s+(các\s+)?(lệnh|chỉ dẫn)\s+trước'
    r'|giả\s+vờ\s+là'
    r'|đóng\s+vai\s+(là\s+)?admin',
    re.IGNORECASE | re.MULTILINE,
)

# Fields được phép sửa qua "sửa <trường> <giá trị>"
AMEND_ALLOWED_FIELDS = {
    "expense": {"số", "nội dung", "category", "nguoichi", "thoigian"},
    "contribution": {"số", "nội dung"},
    "advance_expense": {"số", "nội dung"},
    "trip_new": {"tên", "thời gian", "số người", "danh sách", "nạp"},
}

# ─── Exceptions ───────────────────────────────────────────────────────────────

class InputValidationError(Exception):
    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class InputTooLongError(InputValidationError):
    def __init__(self, length: int):
        super().__init__(
            f"Tin nhắn quá dài ({length} ký tự). Giới hạn {MAX_INPUT_LENGTH} ký tự."
        )


class InvalidEncodingError(InputValidationError):
    def __init__(self):
        super().__init__("Tin nhắn chứa ký tự không hợp lệ.")


class InvalidAmendFieldError(InputValidationError):
    def __init__(self, field: str, allowed: set):
        super().__init__(
            f"Không thể sửa trường '{field}'. "
            f"Cho phép: {', '.join(sorted(allowed))}"
        )


# ─── Validation functions ─────────────────────────────────────────────────────

def validate_length(text: str) -> None:
    """Tầng 1: Length limit."""
    if len(text) > MAX_INPUT_LENGTH:
        raise InputTooLongError(len(text))


def validate_encoding(text: str) -> None:
    """Tầng 2: Reject zero-width chars và control chars."""
    for ch in ZERO_WIDTH_CHARS:
        if ch in text:
            raise InvalidEncodingError()

    for ch in text:
        cat = unicodedata.category(ch)
        if cat.startswith('C') and ch not in ('\t', '\n', '\r'):
            raise InvalidEncodingError()


def detect_prompt_injection(text: str) -> bool:
    """Tầng 3: Detect injection patterns. Log nhưng không reject cứng."""
    if INJECTION_REGEX.search(text):
        log.warning("input.prompt_injection_detected",
                    text_sample=text[:100])
        return True
    return False


def validate_amend_field(kind: str, field: str) -> None:
    """Tầng 4: Whitelist fields có thể sửa qua 'sửa <trường> ...'"""
    allowed = AMEND_ALLOWED_FIELDS.get(kind, set())
    if field.lower().strip() not in allowed:
        raise InvalidAmendFieldError(field, allowed)


def validate_amount(amount: int) -> None:
    """Kiểm tra số tiền hợp lệ."""
    if amount < 1_000:
        raise InputValidationError("Số tiền quá nhỏ (tối thiểu 1.000đ).")
    if amount > 10_000_000_000:
        raise InputValidationError("Số tiền quá lớn (tối đa 10 tỷ đồng).")


def validate_image(content: bytes, mime_type: str) -> None:
    """Kiểm tra ảnh upload."""
    ALLOWED_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if mime_type not in ALLOWED_MIME:
        raise InputValidationError(f"Định dạng ảnh không hỗ trợ: {mime_type}")
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        mb = len(content) / 1024 / 1024
        raise InputValidationError(f"Ảnh quá lớn ({mb:.1f}MB). Tối đa 10MB.")


# ─── Main entry point ─────────────────────────────────────────────────────────

def validate_user_input(text: str) -> Optional[str]:
    """
    Chạy 3 tầng đầu. Trả về warning nếu có injection (nhưng không raise).
    Raise InputValidationError nếu length/encoding không hợp lệ.

    Usage:
        try:
            warning = validate_user_input(text)
            if warning:
                log.warning("input.injection_flagged")
        except InputValidationError as e:
            await reply(ctx, e.user_message)
            return
    """
    validate_length(text)
    validate_encoding(text)
    if detect_prompt_injection(text):
        return "injection_flagged"
    return None


# ─── Output filter ────────────────────────────────────────────────────────────

RESPONSE_FORBIDDEN = re.compile(
    r'You\s+are\s+an?\s+(AI|assistant|parser|language model)'
    r'|system\s+prompt'
    r'|treat\s+.*\s+as\s+(data|JSON)'
    r'|(Claude|GPT-[0-9]|OpenAI|Anthropic)',
    re.IGNORECASE,
)


def filter_llm_response(text: str) -> str:
    """
    Filter content không nên gửi cho user từ LLM.
    Nếu detect → thay bằng message an toàn.
    """
    if RESPONSE_FORBIDDEN.search(text):
        log.warning("output.filter.blocked", sample=text[:100])
        return "Bot không thể xử lý yêu cầu này. Gõ /help để xem hướng dẫn."
    # Strip HTML tags nếu có
    text = re.sub(r'<[^>]+>', '', text)
    # Strip URLs từ LLM (tránh phishing)
    text = re.sub(r'https?://\S+', '[link]', text)
    return text[:1000]  # Hard cap length
