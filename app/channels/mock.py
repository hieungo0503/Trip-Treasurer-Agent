"""
Mock channel — test local mà không cần Zalo OA thật.

Endpoints:
  POST /mock/send      — simulate user gửi text
  POST /mock/send_image — simulate user gửi ảnh (base64 hoặc URL)
  GET  /mock/inbox/{user_id} — xem messages bot đã reply
  DELETE /mock/inbox/{user_id} — clear inbox
  GET  /mock/state/{user_id}  — xem conversation state

Usage:
  curl -X POST http://localhost:8080/mock/send \
       -H "Content-Type: application/json" \
       -d '{"zalo_user_id": "test_user", "text": "chi 500k ăn uống"}'
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import Optional

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

log = structlog.get_logger()

router = APIRouter(prefix="/mock", tags=["mock"])

# In-memory outbox: user_id → list of messages
_inbox: dict[str, list[dict]] = defaultdict(list)


# ── Public send function (gọi từ orchestrator) ────────────────────────────────

async def send_mock_message(zalo_user_id: str, text: str) -> None:
    """Bot gửi reply → lưu vào in-memory inbox."""
    _inbox[zalo_user_id].append({
        "from": "bot",
        "text": text,
        "ts": time.time(),
    })
    log.debug("mock.bot_reply", user=zalo_user_id, text=text[:80])


# ── Request/Response models ───────────────────────────────────────────────────

class MockSendRequest(BaseModel):
    zalo_user_id: str
    text: str


class MockSendImageRequest(BaseModel):
    zalo_user_id: str
    image_url: Optional[str] = None
    image_base64: Optional[str] = None


class MockSendResponse(BaseModel):
    event_id: str
    bot_replies: list[dict]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/send", response_model=MockSendResponse)
async def mock_send_text(body: MockSendRequest) -> MockSendResponse:
    """Simulate user gửi text — trigger toàn bộ agent pipeline."""
    from app.agent.orchestrator import handle_event

    event_id = f"mock-{uuid.uuid4().hex[:8]}"
    event = {
        "event_name": "user_send_text",
        "user_id": body.zalo_user_id,
        "event_id": event_id,
        "timestamp": int(time.time() * 1000),
        "message": {"text": body.text},
    }

    # Clear inbox trước khi xử lý để trả về chỉ reply của request này
    _inbox[body.zalo_user_id].clear()

    await handle_event(event)

    replies = list(_inbox.get(body.zalo_user_id, []))
    return MockSendResponse(event_id=event_id, bot_replies=replies)


@router.post("/send_image", response_model=MockSendResponse)
async def mock_send_image(body: MockSendImageRequest) -> MockSendResponse:
    """Simulate user gửi ảnh bill."""
    from app.agent.orchestrator import handle_event

    event_id = f"mock-img-{uuid.uuid4().hex[:8]}"
    event = {
        "event_name": "user_send_image",
        "user_id": body.zalo_user_id,
        "event_id": event_id,
        "timestamp": int(time.time() * 1000),
        "message": {
            "attachments": [
                {
                    "type": "image",
                    "payload": {
                        "url": body.image_url or "",
                        "base64": body.image_base64 or "",
                    },
                }
            ]
        },
    }

    _inbox[body.zalo_user_id].clear()
    await handle_event(event)

    replies = list(_inbox.get(body.zalo_user_id, []))
    return MockSendResponse(event_id=event_id, bot_replies=replies)


@router.get("/inbox/{user_id}")
async def mock_get_inbox(user_id: str) -> dict:
    return {"user_id": user_id, "messages": list(_inbox.get(user_id, []))}


@router.delete("/inbox/{user_id}")
async def mock_clear_inbox(user_id: str) -> dict:
    _inbox.pop(user_id, None)
    return {"cleared": True}


@router.get("/state/{user_id}")
async def mock_get_state(user_id: str) -> dict:
    from app.storage.db import get_db
    from app.storage.repositories import ConversationRepository, TripRepository

    db = get_db()
    conv_repo = ConversationRepository(db)
    trip_repo = TripRepository(db)

    conv = await conv_repo.get(user_id)
    active_trip = None
    if conv and conv.get("active_trip_id"):
        trip = await trip_repo.get_by_id(conv["active_trip_id"])
        if trip:
            active_trip = {"id": trip.id, "name": trip.name, "status": trip.status.value}

    return {
        "user_id": user_id,
        "conversation": conv,
        "active_trip": active_trip,
    }
