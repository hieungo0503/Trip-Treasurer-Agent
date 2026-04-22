"""
Input validation — 4 tầng filter theo RELIABILITY_SECURITY.md Section B.1.

Tầng 1: Length limit
Tầng 2: Encoding check (zero-width, control chars)
Tầng 3: Prompt injection detect (log only, không reject cứng)
Tầng 4: Amend field whitelist
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

import structlog

log = structlog.get_logger()

MAX_INPUT_LENGTH = 500
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB


class InputValidationError(Exception):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


# ── Tầng 1: Length ──────────────────────────────────────────────────────────

def validate_length(text: str, max_len: int = MAX_INPUT_LENGTH) -> None:
    if len(text) > max_len:
        raise InputValidationError(
            f"Tin nhắn quá dài ({len(text)} ký tự). Giới hạn {max_len} ký tự."
        )


# ── Tầng 2: Encoding ─────────────────────────────────────────────────────────

_ZERO_WIDTH_CHARS = {"​", "‌", "‍", "﻿"}


def validate_encoding(text: str) -> None:
    if any(ch in text for ch in _ZERO_WIDTH_CHARS):
        raise InputValidationError("Tin nhắn chứa ký tự ẩn.")

    for ch in text:
        if unicodedata.category(ch).startswith("C") and ch not in ("\t", "\n", "\r"):
            raise InputValidationError("Tin nhắn chứa ký tự không hợp lệ.")

    # Log nếu trông có vẻ là base64 thuần (suspicious)
    if re.match(r"^[A-Za-z0-9+/=]{20,}$", text.strip()):
        log.warning("input.suspicious_base64", sample=text[:50])


# ── Tầng 3: Prompt injection ─────────────────────────────────────────────────

_INJECTION_REGEX = re.compile(
    r"ignore\s+(previous|prior|above|all)\s+(instruction|prompt)"
    r"|disregard\s+(previous|prior)"
    r"|forget\s+(previous|prior|everything)"
    r"|you\s+are\s+now\s+"
    r"|from\s+now\s+on\s+you"
    r"|act\s+as\s+(a\s+)?(different|admin|system)"
    r"|what\s+(is|are)\s+your\s+(instruction|prompt|system)"
    r"|repeat\s+(the|your)\s+(instruction|prompt|system)"
    r"|bỏ\s+qua\s+(các\s+)?(lệnh|chỉ\s*dẫn)\s+trước"
    r"|giả\s+vờ\s+là"
    r"|đóng\s+vai\s+(là\s+)?admin",
    flags=re.IGNORECASE | re.MULTILINE,
)


def detect_prompt_injection(text: str) -> bool:
    return bool(_INJECTION_REGEX.search(text))


InjectionStatus = Literal["clean", "flagged"]


def validate_injection(text: str) -> InjectionStatus:
    """Không reject cứng — chỉ log + flag để caller quyết định."""
    if detect_prompt_injection(text):
        log.warning("input.prompt_injection_detected", sample=text[:100])
        return "flagged"
    return "clean"


# ── Tầng 4: Amend field whitelist ────────────────────────────────────────────

_AMEND_ALLOWED: dict[str, set[str]] = {
    "expense": {"số", "nội dung", "category", "nguoichi", "thoigian"},
    "contribution": {"số", "nội dung"},
    "advance_expense": {"số", "nội dung"},
    "trip_new": {"tên", "thời gian", "số người", "danh sách", "nạp"},
}


def validate_amend_field(kind: str, field: str) -> None:
    allowed = _AMEND_ALLOWED.get(kind, set())
    if field.lower().strip() not in allowed:
        raise InputValidationError(
            f"Không thể sửa trường '{field}'. Cho phép: {', '.join(sorted(allowed))}."
        )


# ── Validate image ────────────────────────────────────────────────────────────

_ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}


def validate_image(content_type: str, size_bytes: int) -> None:
    if content_type not in _ALLOWED_IMAGE_MIMES:
        raise InputValidationError(
            f"Định dạng ảnh không được hỗ trợ: {content_type}. Dùng JPEG/PNG/WebP."
        )
    if size_bytes > MAX_IMAGE_SIZE_BYTES:
        mb = size_bytes / 1024 / 1024
        raise InputValidationError(f"Ảnh quá lớn ({mb:.1f}MB). Giới hạn 10MB.")


# ── Validate amount ───────────────────────────────────────────────────────────

MIN_AMOUNT = 1_000      # 1k VNĐ
MAX_AMOUNT = 10_000_000_000  # 10 tỷ VNĐ


def validate_amount(amount: int) -> None:
    if amount <= 0:
        raise InputValidationError("Số tiền phải lớn hơn 0.")
    if amount < MIN_AMOUNT:
        raise InputValidationError(f"Số tiền tối thiểu {MIN_AMOUNT:,}đ.")
    if amount > MAX_AMOUNT:
        raise InputValidationError(f"Số tiền vượt giới hạn ({MAX_AMOUNT:,}đ).")


# ── Full pipeline ─────────────────────────────────────────────────────────────

def validate_user_text(text: str) -> InjectionStatus:
    """
    Chạy toàn bộ pipeline validation cho text đầu vào từ user.
    Raise InputValidationError nếu vi phạm tầng 1-2.
    Trả về InjectionStatus cho tầng 3 (caller quyết định xử lý).
    """
    validate_length(text)
    validate_encoding(text)
    return validate_injection(text)
