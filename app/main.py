"""
FastAPI entry point.

Routes:
    POST /webhook/zalo  — nhận webhook từ Zalo OA (Phase 2)
    POST /mock/send     — mock channel để test local (Phase 1)
    GET  /health        — health check
    GET  /metrics       — Prometheus metrics (Phase 3)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.config import get_settings
from app.observability.logging import setup_logging
from app.observability.tracing import setup_tracing
from app.reliability.circuit_breaker import (
    llm_circuit, sheets_circuit, drive_circuit, zalo_circuit
)
from app.storage.db import init_db, get_db

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # 1. Logging
    setup_logging(settings.log_level)

    # 2. Tracing
    setup_tracing(settings.otel_exporter, settings.otel_endpoint)

    # 3. DB
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    import os
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
    await init_db(db_path)

    # 4. Sheet projector background task
    from app.tools.sheet_projector import start_projector_loop, stop_projector
    projector_task = asyncio.create_task(start_projector_loop(interval_seconds=30))

    log.info("app.started", mock_channel=settings.mock_channel_enabled)
    yield

    # Shutdown
    stop_projector()
    projector_task.cancel()
    try:
        await projector_task
    except asyncio.CancelledError:
        pass
    db = get_db()
    await db.close()
    log.info("app.stopped")


app = FastAPI(
    title="Trip Treasurer Agent",
    description="AI Agent quản lý chi tiêu du lịch nhóm qua Zalo",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Mock channel (Phase 1 test) ───────────────────────────────────────────────
from app.channels.mock import router as mock_router
app.include_router(mock_router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    db_ok = True
    try:
        db = get_db()
        await db.fetch_one("SELECT 1")
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "version": "0.1.0",
        "services": {
            "db": "ok" if db_ok else "error",
            "llm": llm_circuit.state.value,
            "sheets": sheets_circuit.state.value,
            "zalo": zalo_circuit.state.value,
        },
    }


# ── Webhook Zalo (Phase 2) ────────────────────────────────────────────────────

@app.post("/webhook/zalo")
async def zalo_webhook(request: Request):
    """
    Phase 2: verify Zalo signature, enqueue, return 200 < 2s.
    Phase 1 placeholder.
    """
    return JSONResponse({"ok": True, "note": "Phase 2 not implemented yet"})


# ── Metrics ───────────────────────────────────────────────────────────────────

@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
