"""
OCR tool — PaddleOCR + LLM vision fallback — Phase 2.

Phase 1: stub trả về kết quả empty với confidence=0.
Phase 2: implement PaddleOCR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()


@dataclass
class OcrResult:
    amount_vnd: Optional[int]
    description: Optional[str]
    merchant: Optional[str]
    confidence: float  # 0.0–1.0
    raw_text: Optional[str] = None


async def ocr_bill_from_url(image_url: str, trace_id: str = "") -> OcrResult:
    """
    OCR ảnh bill từ URL.
    Phase 1: stub trả về empty result.
    """
    log.info("ocr.from_url.stub", trace_id=trace_id)
    return OcrResult(
        amount_vnd=None,
        description=None,
        merchant=None,
        confidence=0.0,
        raw_text=None,
    )


async def ocr_bill_from_base64(image_b64: str, trace_id: str = "") -> OcrResult:
    """
    OCR ảnh bill từ base64.
    Phase 1: stub trả về empty result.
    """
    log.info("ocr.from_base64.stub", trace_id=trace_id)
    return OcrResult(
        amount_vnd=None,
        description=None,
        merchant=None,
        confidence=0.0,
    )
