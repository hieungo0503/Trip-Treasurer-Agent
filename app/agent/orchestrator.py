"""
Agent orchestrator — entry point cho mọi event từ Zalo/mock.

Pipeline:
  1. Validate input
  2. Idempotency check
  3. Resolve user/member/trip context
  4. Classify intent
  5. Dispatch tới node tương ứng
  6. Reply

Phase 1: intent classification + placeholder replies.
Node commit sẽ implement trong Phase 1 tiếp theo.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine, Optional

import structlog

from app.agent.intents import Intent, classify_intent, extract_command_arg
from app.config import get_settings
from app.domain.models import ConversationState, TripStatus
from app.observability.logging import bind_request_context, clear_request_context
from app.observability.metrics import messages_received_total, messages_replied_total
from app.security.input_validation import InputValidationError, validate_user_text
from app.storage.db import get_db
from app.storage.repositories import (
    ConversationRepository,
    MemberRepository,
    TripRepository,
)

log = structlog.get_logger()


@dataclass
class RequestContext:
    """Trạng thái của 1 request trong pipeline."""
    trace_id: str
    event_id: str
    zalo_user_id: str
    member_id: Optional[str] = None
    trip_id: Optional[str] = None
    trip_status: Optional[TripStatus] = None
    conv_state: ConversationState = ConversationState.IDLE
    pending_id: Optional[str] = None
    deadline_at: datetime = field(
        default_factory=lambda: datetime.utcnow() + timedelta(seconds=20)
    )
    _send_fn: Optional[Callable] = field(default=None, repr=False)

    def check_deadline(self, step: str) -> None:
        if datetime.utcnow() >= self.deadline_at:
            raise TimeoutError(f"Budget exhausted at step '{step}'")

    async def reply(self, text: str) -> None:
        if self._send_fn:
            await self._send_fn(self.zalo_user_id, text)
            messages_replied_total.labels(status="ok").inc()
        else:
            log.warning("ctx.no_send_fn", text=text[:80])


def _resolve_send_fn(event_source: str) -> Callable:
    """Trả về send function phù hợp với channel."""
    if event_source == "mock":
        from app.channels.mock import send_mock_message
        return send_mock_message
    # Phase 2: Zalo send
    from app.channels.mock import send_mock_message  # fallback
    return send_mock_message


async def handle_event(event: dict[str, Any]) -> None:
    """
    Entry point. Gọi từ webhook handler hoặc mock channel.
    Không throw — mọi exception bắt và log ở đây.
    """
    event_id = event.get("event_id") or str(uuid.uuid4())
    zalo_user_id = event.get("user_id", "unknown")
    source = event.get("_source", "mock")
    trace_id = str(uuid.uuid4())

    bind_request_context(
        trace_id=trace_id,
        zalo_user_id=zalo_user_id,
    )
    messages_received_total.inc()

    try:
        await _process_event(event, event_id, zalo_user_id, trace_id, source)
    except Exception as e:
        log.error("orchestrator.unhandled_exception", error=str(e), exc_info=True)
        try:
            send_fn = _resolve_send_fn(source)
            await send_fn(zalo_user_id, "⚠️ Bot gặp lỗi, vui lòng thử lại sau.")
            messages_replied_total.labels(status="error").inc()
        except Exception:
            pass
    finally:
        clear_request_context()


async def _process_event(
    event: dict,
    event_id: str,
    zalo_user_id: str,
    trace_id: str,
    source: str,
) -> None:
    db = get_db()
    send_fn = _resolve_send_fn(source)

    # ── 1. Idempotency ──────────────────────────────────────────────────────
    if await db.is_event_processed(event_id):
        log.info("event.duplicate_skipped", event_id=event_id)
        return

    # ── 2. Bot enabled check ────────────────────────────────────────────────
    if await db.get_setting("bot_enabled", "true") != "true":
        log.info("event.bot_paused")
        return

    # ── 3. Resolve member ───────────────────────────────────────────────────
    member_repo = MemberRepository(db)
    member = await member_repo.get_by_zalo_user_id(zalo_user_id)
    is_new_user = member is None

    # ── 4. Resolve conversation state ──────────────────────────────────────
    conv_repo = ConversationRepository(db)
    conv = await conv_repo.get(zalo_user_id)
    conv_state = ConversationState(conv["state"]) if conv else ConversationState.IDLE
    pending_id = conv["pending_id"] if conv else None
    active_trip_id = conv["active_trip_id"] if conv else None

    # Check pending timeout
    if pending_id and conv_state == ConversationState.AWAITING_CONFIRM:
        from app.storage.repositories import PendingRepository
        pending_repo = PendingRepository(db)
        pending = await pending_repo.get(pending_id)
        if pending and pending["expires_at"] < datetime.utcnow().isoformat():
            await pending_repo.cancel(pending_id)
            await conv_repo.set_state(zalo_user_id, "idle", None)
            conv_state = ConversationState.IDLE
            pending_id = None
            await send_fn(zalo_user_id, "⏰ Đã huỷ xác nhận do quá 30 phút không phản hồi.")

    # ── 5. Resolve active trip ──────────────────────────────────────────────
    trip_status = None
    trip_repo = TripRepository(db)

    if member and active_trip_id:
        trip = await trip_repo.get_by_id(active_trip_id)
        if trip and await trip_repo.is_member(active_trip_id, member.id):
            trip_status = trip.status
        else:
            active_trip_id = None
            await conv_repo.set_active_trip(zalo_user_id, None)

    elif member and not active_trip_id:
        active_trips = await trip_repo.get_active_trips_for_member(member.id)
        if len(active_trips) == 1:
            active_trip_id = active_trips[0].id
            trip_status = active_trips[0].status
            await conv_repo.set_active_trip(zalo_user_id, active_trip_id)

    elif is_new_user:
        # User mới chưa có member record — kiểm tra có trip nào đang COLLECTING_TOPUP không.
        # Nếu có → cho intent classifier biết để parse "<tên> đã nạp X".
        collecting_trips = await trip_repo.get_trips_by_status("collecting_topup")
        if collecting_trips:
            trip_status = collecting_trips[0].status
            active_trip_id = collecting_trips[0].id

    ctx = RequestContext(
        trace_id=trace_id,
        event_id=event_id,
        zalo_user_id=zalo_user_id,
        member_id=member.id if member else None,
        trip_id=active_trip_id,
        trip_status=trip_status,
        conv_state=conv_state,
        pending_id=pending_id,
        _send_fn=send_fn,
    )

    # ── 6. Parse message ────────────────────────────────────────────────────
    message = event.get("message", {})
    is_image = bool(message.get("attachments"))
    text = message.get("text", "").strip() if not is_image else ""

    # Input validation
    if text:
        try:
            validate_user_text(text)
        except InputValidationError as e:
            await ctx.reply(e.user_message)
            return

    # ── 7. Classify intent ──────────────────────────────────────────────────
    intent = classify_intent(
        text=text,
        state=conv_state,
        trip_status=trip_status,
        is_image=is_image,
        is_new_user=is_new_user,
    )

    log.info("event.classified", intent=intent.value, user=zalo_user_id)

    # ── 8. Dispatch ─────────────────────────────────────────────────────────
    await _dispatch(ctx, intent, text, event)

    # ── 9. Mark processed ───────────────────────────────────────────────────
    await db.mark_event_processed(event_id)
    await db._conn.commit()


async def _dispatch(
    ctx: RequestContext,
    intent: Intent,
    text: str,
    event: dict,
) -> None:
    """Route intent → handler."""

    # ── Welcome ─────────────────────────────────────────────────────────────
    if intent == Intent.WELCOME:
        await ctx.reply(_load_help("welcome"))
        return

    # ── Help ────────────────────────────────────────────────────────────────
    if intent == Intent.HELP_OVERVIEW:
        await ctx.reply(_load_help("overview"))
        return
    if intent == Intent.HELP_TOPIC:
        topic = extract_command_arg(text, "/help").lower().strip()
        await ctx.reply(_load_help(topic))
        return
    if intent == Intent.HELP_SHARE:
        await ctx.reply(_load_help("share"))
        return

    # ── Guard: cần member ───────────────────────────────────────────────────
    # LOG_INITIAL_TOPUP: user mới chưa có member record vẫn được phép nạp đầu.
    # Handler sẽ tạo member + link zalo_user_id tự động khi tìm thấy placeholder khớp tên.
    # CONFIRM/CANCEL: new user confirming initial_topup has pending_id but no member_id yet
    _no_member_ok = {Intent.WELCOME, Intent.HELP_OVERVIEW, Intent.HELP_TOPIC, Intent.HELP_SHARE, Intent.TRIP_NEW, Intent.LOG_INITIAL_TOPUP, Intent.CONFIRM, Intent.CANCEL_PENDING}
    if ctx.member_id is None and intent not in _no_member_ok:
        await ctx.reply(
            "⚠️ Bạn chưa được thêm vào chuyến nào.\n"
            "Liên hệ admin để được thêm vào chuyến du lịch."
        )
        return

    # ── Guard: cần trip ──────────────────────────────────────────────────────
    # CONFIRM / CANCEL_PENDING không cần trip — pending_id đã đủ để xử lý
    _needs_trip = {
        Intent.LOG_EXPENSE, Intent.LOG_TOPUP, Intent.LOG_ADVANCE_EXPENSE,
        Intent.LOG_INITIAL_TOPUP, Intent.AMEND,
        Intent.QUERY_FUND, Intent.QUERY_SUMMARY,
        Intent.QUERY_MINE, Intent.QUERY_TOPUP_MINE, Intent.QUERY_SETTLEMENT,
        Intent.TRIP_END, Intent.HUY_AUTO_ADVANCE, Intent.REBUILD_SHEET,
    }
    if intent in _needs_trip and not ctx.trip_id:
        await ctx.reply(
            "⚠️ Không có chuyến đang hoạt động.\n"
            "Dùng /trip_new để tạo chuyến mới hoặc /trips để chọn chuyến."
        )
        return

    # ── Confirmation flow ────────────────────────────────────────────────────
    if intent == Intent.CONFIRM:
        await _handle_confirm(ctx)
        return
    if intent == Intent.CANCEL_PENDING:
        await _handle_cancel(ctx)
        return
    if intent == Intent.AMEND:
        await ctx.reply("✏️ Chức năng sửa đang được phát triển. Gõ 'huỷ' để hủy và nhập lại.")
        return

    # ── Trip management ──────────────────────────────────────────────────────
    if intent == Intent.TRIP_NEW:
        await _handle_trip_new(ctx, text)
        return
    if intent == Intent.TRIP_LIST:
        await _handle_trip_list(ctx)
        return
    if intent == Intent.TRIP_VIEW:
        trip_id_arg = extract_command_arg(text, "/trip_view")
        await _handle_trip_view(ctx, trip_id_arg)
        return
    if intent == Intent.TRIP_SWITCH:
        trip_id_arg = extract_command_arg(text, "/trip_switch")
        await _handle_trip_switch(ctx, trip_id_arg)
        return
    if intent == Intent.TRIP_END:
        await _handle_trip_end(ctx)
        return
    if intent == Intent.TRIP_ARCHIVE:
        await _handle_trip_archive(ctx)
        return

    # ── Financial logging ────────────────────────────────────────────────────
    if intent == Intent.LOG_EXPENSE:
        await _handle_log_expense(ctx, text)
        return
    if intent == Intent.LOG_TOPUP:
        await _handle_log_topup(ctx, text)
        return
    if intent == Intent.LOG_ADVANCE_EXPENSE:
        await _handle_log_advance_expense(ctx, text)
        return
    if intent == Intent.LOG_INITIAL_TOPUP:
        await _handle_initial_topup(ctx, text)
        return
    if intent == Intent.LOG_EXPENSE_IMAGE:
        await _handle_log_expense_image(ctx, event)
        return

    # ── Query ────────────────────────────────────────────────────────────────
    if intent == Intent.QUERY_FUND:
        await _handle_query_fund(ctx)
        return
    if intent == Intent.QUERY_SUMMARY:
        await _handle_query_summary(ctx)
        return
    if intent == Intent.QUERY_MINE:
        await _handle_query_mine(ctx)
        return
    if intent == Intent.QUERY_TOPUP_MINE:
        await _handle_query_topup_mine(ctx)
        return
    if intent == Intent.QUERY_SETTLEMENT:
        await _handle_query_settlement(ctx)
        return

    # ── Admin ────────────────────────────────────────────────────────────────
    if intent == Intent.PAUSE_BOT:
        await _handle_pause_bot(ctx)
        return
    if intent == Intent.RESUME_BOT:
        await _handle_resume_bot(ctx)
        return
    if intent == Intent.HUY_AUTO_ADVANCE:
        expense_id = extract_command_arg(text, "/huy_auto")
        await _handle_huy_auto_advance(ctx, expense_id)
        return
    if intent == Intent.REBUILD_SHEET:
        await _handle_rebuild_sheet(ctx)
        return

    # ── Unknown / LLM fallback ───────────────────────────────────────────────
    if intent == Intent.UNKNOWN:
        from app.tools.llm import classify_unknown_intent
        llm_intent = await classify_unknown_intent(text, ctx.trace_id)
        if llm_intent != "unknown":
            log.info("intent.llm_resolved", llm_intent=llm_intent)
        await ctx.reply(
            "🤔 Bot chưa hiểu ý bạn.\n"
            "Thử: 'chi 500k ăn uống', 'nạp 200k', hoặc gõ /help để xem hướng dẫn."
        )
        return

    await ctx.reply(f"⚙️ Chức năng '{intent.value}' đang được phát triển.")


# ── Handlers ─────────────────────────────────────────────────────────────────

async def _handle_confirm(ctx: RequestContext) -> None:
    if not ctx.pending_id:
        await ctx.reply("Không có giao dịch nào đang chờ xác nhận.")
        return
    db = get_db()
    from app.storage.repositories import PendingRepository
    pending = await PendingRepository(db).get(ctx.pending_id)
    if not pending:
        await ctx.reply("Giao dịch đã hết hạn hoặc không tồn tại.")
        return

    kind = pending["kind"]
    try:
        if kind == "expense":
            from app.agent.nodes.commit_expense import commit_expense
            reply = await commit_expense(ctx, pending)
        elif kind == "contribution":
            from app.agent.nodes.commit_topup import commit_topup
            reply = await commit_topup(ctx, pending)
        elif kind == "advance_expense":
            from app.agent.nodes.commit_advance_expense import commit_advance_expense
            reply = await commit_advance_expense(ctx, pending)
        elif kind == "initial_topup":
            from app.agent.nodes.commit_initial_topup import commit_initial_topup
            reply = await commit_initial_topup(ctx, pending)
        elif kind == "trip_new":
            from app.agent.nodes.commit_trip import commit_trip
            reply = await commit_trip(ctx, pending)
        else:
            await ctx.reply(f"⚙️ Loại giao dịch '{kind}' chưa được hỗ trợ.")
            return
        await db._conn.commit()
        await ctx.reply(reply)
    except RuntimeError as e:
        await db._conn.rollback()
        log.error("handle_confirm.commit_failed", kind=kind, error=str(e))
        await ctx.reply("⚠️ Ghi thất bại do lỗi dữ liệu. Vui lòng thử lại.")


async def _handle_cancel(ctx: RequestContext) -> None:
    if not ctx.pending_id:
        await ctx.reply("Không có giao dịch nào đang chờ huỷ.")
        return
    db = get_db()
    from app.storage.repositories import PendingRepository, ConversationRepository
    await PendingRepository(db).cancel(ctx.pending_id)
    await ConversationRepository(db).set_state(ctx.zalo_user_id, "idle", None)
    await db._conn.commit()
    await ctx.reply("❌ Đã huỷ xác nhận.")


async def _handle_trip_list(ctx: RequestContext) -> None:
    db = get_db()
    trip_repo = TripRepository(db)
    member_repo = MemberRepository(db)
    member = await member_repo.get_by_zalo_user_id(ctx.zalo_user_id)
    if not member:
        await ctx.reply("Bạn chưa có trong hệ thống.")
        return

    trips = await trip_repo.get_all_trips_for_member(member.id)
    if not trips:
        await ctx.reply("Bạn chưa tham gia chuyến nào. Dùng /trip_new để tạo chuyến mới.")
        return

    lines = ["📚 CÁC CHUYẾN CỦA BẠN\n─────────────────────"]
    active = [t for t in trips if t.status.value == "active"]
    others = [t for t in trips if t.status.value != "active"]

    if active:
        lines.append("🟢 ĐANG HOẠT ĐỘNG:")
        for t in active:
            lines.append(f"  [{t.id}] {t.name}")
            lines.append(f"  {t.start_date.strftime('%d/%m/%Y')}")
            if t.sheet_url:
                lines.append(f"  📎 {t.sheet_url}")

    if others:
        lines.append("\n🔵 ĐÃ KẾT THÚC/LƯU TRỮ:")
        for t in others[:5]:
            lines.append(f"  [{t.id}] {t.name} ({t.status.value})")

    lines.append("\n💡 /trip_view <id>  xem chi tiết")
    await ctx.reply("\n".join(lines))


async def _handle_trip_view(ctx: RequestContext, trip_id: str) -> None:
    if not trip_id:
        await ctx.reply("Dùng: /trip_view <TRIP-ID>")
        return
    db = get_db()
    trip = await TripRepository(db).get_by_id(trip_id)
    if not trip:
        await ctx.reply(f"Không tìm thấy chuyến '{trip_id}'.")
        return
    lines = [
        f"🧳 {trip.name}",
        f"📅 {trip.start_date.strftime('%d/%m/%Y')}",
        f"🔖 Trạng thái: {trip.status.value}",
    ]
    if trip.sheet_url:
        lines.append(f"📊 Sheet: {trip.sheet_url}")
    await ctx.reply("\n".join(lines))


async def _handle_log_expense(ctx: RequestContext, text: str) -> None:
    from app.tools.llm import parse_expense
    from app.utils.money import format_money
    from app.storage.repositories import PendingRepository, ConversationRepository
    from app.storage.repositories.expense_repo import ExpenseRepository, ContributionRepository
    from app.domain.fund import compute_fund_balance

    ctx.check_deadline("parse_expense")
    parsed = await parse_expense(text, ctx.trace_id)

    if not parsed.amount_vnd:
        await ctx.reply(
            "Bot không đọc được số tiền. Thử: 'chi 500k ăn uống' hoặc 'trả 1tr5 khách sạn'"
        )
        return

    db = get_db()
    expenses = await ExpenseRepository(db).list_active(ctx.trip_id)
    contribs = await ContributionRepository(db).list_active(ctx.trip_id)
    from app.domain.fund import check_expense_against_fund
    check = check_expense_against_fund(parsed.amount_vnd, contribs, expenses)

    fund_after_display = check.fund_after_if_paid if check.can_pay_from_fund else 0
    degraded_note = " ⚠️ (parse đơn giản)" if parsed.degraded_mode else ""

    member_repo = MemberRepository(db)
    member = await member_repo.get_by_id(ctx.member_id)
    payer_name = member.display_name if member else "Bạn"

    trip_member_ids = await TripRepository(db).get_member_ids(ctx.trip_id)

    # Build pending payload
    import json as _json
    from datetime import datetime as _dt
    pending_payload = {
        "amount_vnd": parsed.amount_vnd,
        "description": parsed.description or text,
        "category": parsed.category.value,
        "payer_id": ctx.member_id,
        "payer_display_name": payer_name,
        "split_member_ids": trip_member_ids,
        "occurred_at": _dt.utcnow().isoformat(),
        "source": "text",
        "source_raw": text,
        "fund_before": check.fund_current,
        "fund_after": fund_after_display,
        "auto_advance_amount": check.deficit if not check.can_pay_from_fund else None,
    }

    expires_at = _dt.utcnow() + timedelta(minutes=get_settings().pending_expiry_minutes)
    pending_repo = PendingRepository(db)
    pending_id = await pending_repo.insert(
        zalo_user_id=ctx.zalo_user_id,
        kind="expense",
        payload=pending_payload,
        expires_at=expires_at,
        trip_id=ctx.trip_id,
    )
    await ConversationRepository(db).set_state(ctx.zalo_user_id, "awaiting_confirm", pending_id)
    await db._conn.commit()

    # Render confirm card
    from app.utils.money import format_money_compact
    n_split = len(trip_member_ids)
    card_lines = [
        "┌──────────────────────────────────┐",
        "│ ⚠️  Xác nhận khoản chi            │",
        "│ ─────────────────────────────── │",
        f"│ 💰 Số tiền:   {format_money(parsed.amount_vnd)}{degraded_note}",
        f"│ 📝 Nội dung:  {(parsed.description or text)[:30]}",
        f"│ 👤 Người chi: {payer_name}",
        f"│ 👥 Chia cho:  {n_split} người",
        "│ ─────────────────────────────── │",
        f"│ 💳 Quỹ hiện tại: {format_money(check.fund_current)}",
    ]
    if not check.can_pay_from_fund:
        card_lines.append(f"│ ⚠️  Quỹ không đủ! Thiếu: {format_money(check.deficit)}")
        card_lines.append(f"│ 🔴 Bot sẽ tự ghi ứng {format_money(check.deficit)} cho {payer_name}")
    else:
        card_lines.append(f"│ 💳 Sau khi chi:  {format_money(fund_after_display)}")
    card_lines += [
        "│ ─────────────────────────────── │",
        '│ ✅ "ok" để ghi / ❌ "huỷ"       │',
        "└──────────────────────────────────┘",
    ]
    await ctx.reply("\n".join(card_lines))


async def _handle_log_topup(ctx: RequestContext, text: str) -> None:
    from app.tools.llm import parse_topup
    from app.utils.money import format_money
    from app.storage.repositories import PendingRepository, ConversationRepository
    from datetime import datetime as _dt

    ctx.check_deadline("parse_topup")
    parsed = await parse_topup(text, ctx.trace_id)

    if not parsed.amount_vnd:
        await ctx.reply("Bot không đọc được số tiền. Thử: 'nạp 500k' hoặc 'góp 1tr'")
        return

    member_repo = MemberRepository(get_db())
    member = await member_repo.get_by_id(ctx.member_id)
    member_name = member.display_name if member else "Bạn"

    db = get_db()
    from app.storage.repositories.expense_repo import ExpenseRepository, ContributionRepository
    contribs = await ContributionRepository(db).list_active(ctx.trip_id)
    expenses = await ExpenseRepository(db).list_active(ctx.trip_id)
    from app.domain.fund import compute_fund_balance
    fund_now = compute_fund_balance(contribs, expenses)
    fund_after = fund_now + parsed.amount_vnd

    pending_payload = {
        "amount_vnd": parsed.amount_vnd,
        "kind": "extra_topup",
        "member_id": ctx.member_id,
        "member_display_name": member_name,
        "occurred_at": _dt.utcnow().isoformat(),
        "fund_before": fund_now,
        "fund_after": fund_after,
    }

    expires_at = _dt.utcnow() + timedelta(minutes=get_settings().pending_expiry_minutes)
    pending_id = await PendingRepository(db).insert(
        zalo_user_id=ctx.zalo_user_id,
        kind="contribution",
        payload=pending_payload,
        expires_at=expires_at,
        trip_id=ctx.trip_id,
    )
    await ConversationRepository(db).set_state(ctx.zalo_user_id, "awaiting_confirm", pending_id)
    await db._conn.commit()

    await ctx.reply(
        f"┌──────────────────────────────────┐\n"
        f"│ ⚠️  Xác nhận nạp quỹ              │\n"
        f"│ 💰 Số tiền:  {format_money(parsed.amount_vnd)}\n"
        f"│ 👤 Người nạp: {member_name}\n"
        f"│ 💳 Quỹ hiện tại: {format_money(fund_now)}\n"
        f"│ 💳 Sau khi nạp: {format_money(fund_after)}\n"
        f'│ ✅ "ok" để ghi / ❌ "huỷ"       │\n'
        f"└──────────────────────────────────┘"
    )


async def _handle_log_advance_expense(ctx: RequestContext, text: str) -> None:
    from app.tools.llm import parse_advance_expense
    from app.utils.money import format_money
    from app.storage.repositories import PendingRepository, ConversationRepository
    from app.storage.repositories.expense_repo import ExpenseRepository, ContributionRepository
    from app.domain.fund import compute_fund_balance
    from datetime import datetime as _dt

    ctx.check_deadline("parse_advance_expense")
    parsed = await parse_advance_expense(text, ctx.trace_id)

    if not parsed.amount_vnd:
        await ctx.reply("Bot không đọc được. Thử: 'ứng 500k để chi thuê xe'")
        return

    member_repo = MemberRepository(get_db())
    member = await member_repo.get_by_id(ctx.member_id)
    member_name = member.display_name if member else "Bạn"

    db = get_db()
    contribs = await ContributionRepository(db).list_active(ctx.trip_id)
    expenses = await ExpenseRepository(db).list_active(ctx.trip_id)
    fund_now = compute_fund_balance(contribs, expenses)
    trip_member_ids = await TripRepository(db).get_member_ids(ctx.trip_id)

    pending_payload = {
        "amount_vnd": parsed.amount_vnd,
        "description": parsed.description or text,
        "category": parsed.category.value,
        "payer_id": ctx.member_id,
        "payer_display_name": member_name,
        "split_member_ids": trip_member_ids,
        "occurred_at": _dt.utcnow().isoformat(),
        "fund_unchanged": fund_now,
    }

    expires_at = _dt.utcnow() + timedelta(minutes=get_settings().pending_expiry_minutes)
    pending_id = await PendingRepository(db).insert(
        zalo_user_id=ctx.zalo_user_id,
        kind="advance_expense",
        payload=pending_payload,
        expires_at=expires_at,
        trip_id=ctx.trip_id,
    )
    await ConversationRepository(db).set_state(ctx.zalo_user_id, "awaiting_confirm", pending_id)
    await db._conn.commit()

    await ctx.reply(
        f"┌────────────────────────────────────────┐\n"
        f"│ ⚠️  Xác nhận: Ứng tiền + Chi tiêu      │\n"
        f"│ 💰 Số tiền:    {format_money(parsed.amount_vnd)}\n"
        f"│ 📝 Nội dung:   {(parsed.description or text)[:30]}\n"
        f"│ 👤 Người ứng:  {member_name} (ứng tiền túi)\n"
        f"│ ─────────────────────────────────────── │\n"
        f"│ 💳 Quỹ KHÔNG thay đổi (vẫn {format_money(fund_now)})\n"
        f'│ ✅ "ok" / ❌ "huỷ"                     │\n'
        f"└────────────────────────────────────────┘"
    )


async def _handle_query_fund(ctx: RequestContext) -> None:
    from app.storage.repositories.expense_repo import ExpenseRepository, ContributionRepository
    from app.domain.fund import compute_fund_snapshot
    from app.utils.money import format_money

    db = get_db()
    expenses = await ExpenseRepository(db).list_active(ctx.trip_id)
    contribs = await ContributionRepository(db).list_active(ctx.trip_id)
    snapshot = compute_fund_snapshot(contribs, expenses)

    trip = await TripRepository(db).get_by_id(ctx.trip_id)
    trip_name = trip.name if trip else ctx.trip_id

    await ctx.reply(
        f"💰 QUỸ CHUYẾN: {trip_name}\n"
        f"─────────────────────\n"
        f"Tổng đã nạp:  {format_money(snapshot.total_topup)}\n"
        f"Tổng đã chi:  {format_money(snapshot.total_expense)}\n"
        f"Đã ứng:       {format_money(snapshot.total_advance)}\n"
        f"─────────────────────\n"
        f"Còn lại: {format_money(snapshot.fund_balance)}"
    )


# ── Help loader ──────────────────────────────────────────────────────────────

def _load_help(topic: str) -> str:
    """Load help file từ app/help/. Fallback overview nếu không tìm thấy."""
    import os
    help_dir = os.path.join(os.path.dirname(__file__), "..", "help")
    # Map alias
    alias: dict[str, str] = {
        "chi": "chi", "nap": "nap", "nạp": "nap",
        "ung": "ung", "ứng": "ung",
        "anh": "anh", "ảnh": "anh", "bill": "anh",
        "admin": "admin", "chiatien": "chiatien", "chia": "chiatien",
        "share": "share",
    }
    slug = alias.get(topic.lower(), topic.lower())
    path = os.path.join(help_dir, f"{slug}.md")
    if not os.path.exists(path):
        path = os.path.join(help_dir, "overview.md")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "📖 Gõ /help để xem hướng dẫn sử dụng."


# ── New handlers ──────────────────────────────────────────────────────────────

async def _handle_trip_new(ctx: RequestContext, text: str) -> None:
    """Parse /trip_new, resolve members, build confirm card."""
    from app.tools.llm import parse_trip_new
    from app.domain.member_resolver import resolve_members_for_trip
    from app.storage.repositories import PendingRepository, ConversationRepository

    ctx.check_deadline("parse_trip_new")
    parsed = await parse_trip_new(text, ctx.trace_id)

    if parsed.missing_fields:
        missing_str = ", ".join(parsed.missing_fields)
        await ctx.reply(
            f"Thiếu thông tin: {missing_str}.\n\n"
            "Cú pháp:\n"
            "/trip_new <tên>, <ngày>, <N người> gồm <danh sách tên>, <số tiền>/người\n\n"
            "VD: /trip_new Đà Lạt, 10-12/05, 4 người gồm đức hà long minh, 1tr/người"
        )
        return

    db = get_db()
    member_repo = MemberRepository(db)

    async def search_fn(name: str) -> list:
        return await member_repo.get_by_display_name(name)

    from app.domain.member_resolver import AmbiguousNameError, DuplicateNameInTripError
    try:
        plan = await resolve_members_for_trip(parsed.member_names or [], search_fn)
    except DuplicateNameInTripError as e:
        await ctx.reply(f"⚠️ Tên trùng trong danh sách: '{e.name}'. Vui lòng đặt tên khác nhau.")
        return

    if plan.has_ambiguous:
        ambig = next(r for r in plan.resolutions if r.is_ambiguous)
        from app.domain.member_resolver import format_ambiguous_card
        await ctx.reply(format_ambiguous_card(ambig.input_name, ambig.ambiguous_candidates))
        return

    # Build resolved_members list for pending payload
    resolved = []
    for r in plan.resolutions:
        if r.is_new:
            resolved.append({"name": r.input_name, "is_new": True})
        else:
            resolved.append({
                "name": r.input_name,
                "member_id": r.resolved_member.id,
                "is_new": False,
            })

    from app.utils.money import format_money
    n = parsed.expected_member_count or len(parsed.member_names or [])
    topup = parsed.amount_per_person or 0

    pending_payload = {
        "name": parsed.name,
        "start_date": parsed.start_date if isinstance(parsed.start_date, str) else (parsed.start_date.isoformat() if parsed.start_date else None),
        "end_date": parsed.end_date if isinstance(parsed.end_date, str) else (parsed.end_date.isoformat() if parsed.end_date else None),
        "expected_member_count": n,
        "initial_topup_per_member": topup,
        "member_names": parsed.member_names,
        "resolved_members": resolved,
    }

    expires_at = datetime.utcnow() + timedelta(minutes=get_settings().pending_expiry_minutes)
    pending_id = await PendingRepository(db).insert(
        zalo_user_id=ctx.zalo_user_id,
        kind="trip_new",
        payload=pending_payload,
        expires_at=expires_at,
    )
    await ConversationRepository(db).set_state(ctx.zalo_user_id, "awaiting_confirm", pending_id)
    await db._conn.commit()

    member_lines = []
    for r in plan.resolutions:
        tag = "✨ mới" if r.is_new else "♻️ đã có"
        member_lines.append(f"   • {r.input_name} ({tag})")

    card = (
        "┌──────────────────────────────────────┐\n"
        "│ 🧳 XÁC NHẬN TẠO CHUYẾN               │\n"
        f"│ 📍 Tên:        {(parsed.name or '')[:20]}\n"
        f"│ 📅 Ngày:       {(str(pending_payload['start_date'] or '')[:10])}\n"
        f"│ 👥 Thành viên ({n} người):\n"
        + "\n".join(member_lines) + "\n"
        f"│ 💰 Nạp đầu:    {format_money(topup)}/người\n"
        f"│ 💳 Quỹ dự kiến: {format_money(topup * n)}\n"
        "│ ─────────────────────────────────────── │\n"
        '│ ✅ "ok" / ❌ "huỷ"                     │\n'
        "└──────────────────────────────────────┘"
    )
    await ctx.reply(card)


async def _handle_initial_topup(ctx: RequestContext, text: str) -> None:
    """Parse tin '<tên> đã nạp X', tìm member, build confirm card."""
    from app.tools.llm import parse_initial_topup
    from app.storage.repositories import PendingRepository, ConversationRepository
    from app.domain.fuzzy_match import normalize_vn

    ctx.check_deadline("parse_initial_topup")
    parsed = await parse_initial_topup(text, ctx.trace_id)

    if not parsed.amount_vnd or not parsed.member_name:
        await ctx.reply(
            "Bot không đọc được. Thử:\n"
            "'<tên của bạn> đã nạp <số tiền>'\n"
            "VD: Hà đã nạp 1tr"
        )
        return

    db = get_db()
    member_repo = MemberRepository(db)
    trip_repo = TripRepository(db)

    # Find member by name (fuzzy)
    candidates = await member_repo.get_by_display_name(parsed.member_name)
    if not candidates:
        # Fuzzy search
        all_members = await member_repo.get_all_active()
        from app.domain.fuzzy_match import match_member_name
        names = [m.display_name for m in all_members]
        mr = match_member_name(parsed.member_name, names)
        candidates = [m for m in all_members if m.display_name == mr.matched_name] if mr.matched_name else []

    if not candidates:
        await ctx.reply(
            f"⚠️ Không tìm thấy thành viên '{parsed.member_name}' trong chuyến.\n"
            "Liên hệ admin để được thêm vào."
        )
        return

    member = candidates[0]
    trip = await trip_repo.get_by_id(ctx.trip_id) if ctx.trip_id else None

    from app.storage.repositories.expense_repo import ExpenseRepository, ContributionRepository
    from app.domain.fund import compute_fund_balance
    contribs = await ContributionRepository(db).list_active(ctx.trip_id) if ctx.trip_id else []
    expenses = await ExpenseRepository(db).list_active(ctx.trip_id) if ctx.trip_id else []
    fund_now = compute_fund_balance(contribs, expenses)
    fund_after = fund_now + parsed.amount_vnd

    from app.utils.money import format_money
    pending_payload = {
        "amount_vnd": parsed.amount_vnd,
        "kind": "initial_topup",
        "member_id": member.id,
        "member_display_name": member.display_name,
        "trip_id": ctx.trip_id,
        "occurred_at": datetime.utcnow().isoformat(),
        "fund_before": fund_now,
        "fund_after": fund_after,
    }

    expires_at = datetime.utcnow() + timedelta(minutes=get_settings().pending_expiry_minutes)
    pending_id = await PendingRepository(db).insert(
        zalo_user_id=ctx.zalo_user_id,
        kind="initial_topup",
        payload=pending_payload,
        expires_at=expires_at,
        trip_id=ctx.trip_id,
    )
    await ConversationRepository(db).set_state(ctx.zalo_user_id, "awaiting_confirm", pending_id)
    await db._conn.commit()

    trip_name = trip.name if trip else (ctx.trip_id or "chuyến")
    await ctx.reply(
        f"┌──────────────────────────────────┐\n"
        f"│ ⚠️  Xác nhận nạp đầu chuyến       │\n"
        f"│ 🧳 Chuyến:    {trip_name[:20]}\n"
        f"│ 💰 Số tiền:   {format_money(parsed.amount_vnd)}\n"
        f"│ 👤 Thành viên: {member.display_name}\n"
        f"│ 💳 Quỹ sau:   {format_money(fund_after)}\n"
        f'│ ✅ "ok" / ❌ "huỷ"               │\n'
        f"└──────────────────────────────────┘"
    )


async def _handle_log_expense_image(ctx: RequestContext, event: dict) -> None:
    """Xử lý ảnh bill — OCR + confirm card."""
    from app.tools.ocr import ocr_bill_from_url, ocr_bill_from_base64

    attachments = event.get("message", {}).get("attachments", [])
    if not attachments:
        await ctx.reply("Không đọc được ảnh. Hãy gửi ảnh bill rõ hơn hoặc nhập tay.")
        return

    att = attachments[0].get("payload", {})
    image_url = att.get("url", "")
    image_b64 = att.get("base64", "")

    ctx.check_deadline("ocr")
    if image_url:
        result = await ocr_bill_from_url(image_url, ctx.trace_id)
    else:
        result = await ocr_bill_from_base64(image_b64, ctx.trace_id)

    if not result.amount_vnd or result.confidence < 0.3:
        await ctx.reply(
            "📸 Bot không đọc được bill.\n"
            f"(Độ tin cậy OCR: {result.confidence:.0%})\n\n"
            "Vui lòng nhập tay:\n"
            "VD: chi 500k ăn uống"
        )
        return

    # Tạo pending expense từ OCR result
    from app.utils.money import format_money
    from app.storage.repositories import PendingRepository, ConversationRepository
    from app.storage.repositories.expense_repo import ExpenseRepository, ContributionRepository
    from app.domain.fund import check_expense_against_fund

    db = get_db()
    expenses = await ExpenseRepository(db).list_active(ctx.trip_id)
    contribs = await ContributionRepository(db).list_active(ctx.trip_id)
    check = check_expense_against_fund(result.amount_vnd, contribs, expenses)

    member = await MemberRepository(db).get_by_id(ctx.member_id)
    payer_name = member.display_name if member else "Bạn"
    trip_member_ids = await TripRepository(db).get_member_ids(ctx.trip_id)

    pending_payload = {
        "amount_vnd": result.amount_vnd,
        "description": result.description or result.merchant or "Bill (OCR)",
        "category": "other",
        "payer_id": ctx.member_id,
        "payer_display_name": payer_name,
        "split_member_ids": trip_member_ids,
        "occurred_at": datetime.utcnow().isoformat(),
        "source": "image_ocr",
        "ocr_confidence": result.confidence,
        "fund_before": check.fund_current,
        "fund_after": check.fund_after_if_paid if check.can_pay_from_fund else 0,
        "auto_advance_amount": check.deficit if not check.can_pay_from_fund else None,
    }

    expires_at = datetime.utcnow() + timedelta(minutes=get_settings().pending_expiry_minutes)
    pending_id = await PendingRepository(db).insert(
        zalo_user_id=ctx.zalo_user_id,
        kind="expense",
        payload=pending_payload,
        expires_at=expires_at,
        trip_id=ctx.trip_id,
    )
    await ConversationRepository(db).set_state(ctx.zalo_user_id, "awaiting_confirm", pending_id)
    await db._conn.commit()

    conf_pct = f"{result.confidence:.0%}"
    await ctx.reply(
        f"📸 Đọc bill (độ tin cậy: {conf_pct}):\n"
        f"💰 {format_money(result.amount_vnd)}"
        + (f" — {result.description or result.merchant}" if (result.description or result.merchant) else "") + "\n"
        f"👤 Người chi: {payer_name}\n"
        f"💳 Quỹ còn: {format_money(check.fund_current)}\n"
        '✅ "ok" để ghi / ❌ "huỷ"'
        + ("\n⚠️ Nếu sai, gõ 'huỷ' và nhập tay." if result.confidence < 0.7 else "")
    )


async def _handle_query_summary(ctx: RequestContext) -> None:
    from app.storage.repositories.expense_repo import ExpenseRepository, ContributionRepository
    from app.domain.fund import compute_fund_snapshot, compute_all_member_balances
    from app.utils.money import format_money

    db = get_db()
    expenses = await ExpenseRepository(db).list_active(ctx.trip_id)
    contribs = await ContributionRepository(db).list_active(ctx.trip_id)
    snapshot = compute_fund_snapshot(contribs, expenses)

    trip = await TripRepository(db).get_by_id(ctx.trip_id)
    trip_name = trip.name if trip else ctx.trip_id

    member_ids = await TripRepository(db).get_member_ids(ctx.trip_id)
    members = []
    for mid in member_ids:
        m = await MemberRepository(db).get_by_id(mid)
        if m:
            members.append((m.id, m.display_name))

    balances = compute_all_member_balances(members, contribs, expenses)

    lines = [
        f"📊 TỔNG KẾT: {trip_name}",
        "─────────────────────",
        f"Tổng đã nạp:  {format_money(snapshot.total_topup)}",
        f"Tổng đã chi:  {format_money(snapshot.total_expense)}",
        f"Tổng đã ứng:  {format_money(snapshot.total_advance)}",
        f"Quỹ còn lại:  {format_money(snapshot.fund_balance)}",
        "─────────────────────",
        "VỊ THẾ TỪNG NGƯỜI:",
    ]
    for b in sorted(balances, key=lambda x: x.net, reverse=True):
        sign = "+" if b.net >= 0 else ""
        lines.append(f"  {b.display_name}: {sign}{format_money(b.net)}")

    await ctx.reply("\n".join(lines))


async def _handle_query_mine(ctx: RequestContext) -> None:
    from app.storage.repositories.expense_repo import ExpenseRepository
    from app.utils.money import format_money

    db = get_db()
    all_expenses = await ExpenseRepository(db).list_active(ctx.trip_id)
    mine = [e for e in all_expenses if e.payer_id == ctx.member_id]

    if not mine:
        await ctx.reply("Bạn chưa ghi khoản chi nào trong chuyến này.")
        return

    total = sum(e.amount_vnd for e in mine)
    lines = [f"📋 CHI TIÊU CỦA BẠN ({len(mine)} khoản):"]
    for e in mine[-10:]:  # hiện 10 gần nhất
        lines.append(f"  • {format_money(e.amount_vnd)} — {e.description[:30]}")
    if len(mine) > 10:
        lines.append(f"  ... (+{len(mine) - 10} khoản nữa)")
    lines.append(f"  ─────────────────────")
    lines.append(f"  Tổng: {format_money(total)}")
    await ctx.reply("\n".join(lines))


async def _handle_query_topup_mine(ctx: RequestContext) -> None:
    from app.storage.repositories.expense_repo import ContributionRepository
    from app.utils.money import format_money

    db = get_db()
    all_contribs = await ContributionRepository(db).list_active(ctx.trip_id)
    mine = [c for c in all_contribs if c.member_id == ctx.member_id]

    if not mine:
        await ctx.reply("Bạn chưa có lịch sử nạp quỹ trong chuyến này.")
        return

    total = sum(c.amount_vnd for c in mine)
    lines = [f"💰 LỊCH SỬ NẠP QUỸ CỦA BẠN ({len(mine)} lần):"]
    for c in mine:
        lines.append(f"  • {format_money(c.amount_vnd)} ({c.kind.value})")
    lines += ["  ─────────────────────", f"  Tổng: {format_money(total)}"]
    await ctx.reply("\n".join(lines))


async def _handle_query_settlement(ctx: RequestContext) -> None:
    from app.storage.repositories.expense_repo import ExpenseRepository, ContributionRepository
    from app.domain.fund import compute_fund_balance, compute_all_member_balances
    from app.domain.settlement import compute_settlement
    from app.utils.money import format_money

    db = get_db()
    expenses = await ExpenseRepository(db).list_active(ctx.trip_id)
    contribs = await ContributionRepository(db).list_active(ctx.trip_id)

    member_ids = await TripRepository(db).get_member_ids(ctx.trip_id)
    members = []
    for mid in member_ids:
        m = await MemberRepository(db).get_by_id(mid)
        if m:
            members.append((m.id, m.display_name))

    balances = compute_all_member_balances(members, contribs, expenses)
    fund_remain = compute_fund_balance(contribs, expenses)

    # Admin = creator hoặc member đầu tiên
    trip = await TripRepository(db).get_by_id(ctx.trip_id)
    admin_id = trip.created_by if trip else (members[0][0] if members else "")
    admin_name = next((name for mid, name in members if mid == admin_id), "Admin")

    result = compute_settlement(ctx.trip_id, balances, fund_remain, admin_id, admin_name)

    if not result.transfers and not result.refunds:
        await ctx.reply(f"✅ Mọi người đã hòa! Quỹ còn: {format_money(fund_remain)}")
        return

    lines = ["🧮 ĐỀ XUẤT CHIA TIỀN:", "─────────────────────"]
    for t in result.transfers:
        lines.append(f"  {t.from_display_name} → {t.to_display_name}: {format_money(t.amount_vnd)}")
    if result.refunds:
        lines.append("─────────────────────")
        lines.append("Hoàn quỹ:")
        for r in result.refunds:
            lines.append(f"  {r.to_display_name} được hoàn: {format_money(r.amount_vnd)}")
    lines.append(f"\n💳 Quỹ còn lại: {format_money(fund_remain)}")
    await ctx.reply("\n".join(lines))


async def _handle_trip_switch(ctx: RequestContext, trip_id: str) -> None:
    if not trip_id:
        await ctx.reply("Dùng: /trip_switch <TRIP-ID>")
        return
    db = get_db()
    trip = await TripRepository(db).get_by_id(trip_id)
    if not trip:
        await ctx.reply(f"Không tìm thấy chuyến '{trip_id}'.")
        return
    if not await TripRepository(db).is_member(trip_id, ctx.member_id):
        await ctx.reply("⛔ Bạn không phải thành viên của chuyến này.")
        return
    await ConversationRepository(db).set_active_trip(ctx.zalo_user_id, trip_id)
    await db._conn.commit()
    await ctx.reply(f"✅ Đã chuyển sang: {trip.name} [{trip_id}]")


async def _handle_trip_end(ctx: RequestContext) -> None:
    from app.security.permissions import require_admin
    db = get_db()
    trip = await TripRepository(db).get_by_id(ctx.trip_id)
    if not trip:
        await ctx.reply("Không tìm thấy chuyến.")
        return
    if ctx.member_id not in get_settings().admin_member_id_list:
        # Also allow trip creator
        if trip.created_by != ctx.member_id:
            await ctx.reply("⛔ Chỉ admin hoặc người tạo chuyến mới có thể kết thúc.")
            return
    await TripRepository(db).set_settled(ctx.trip_id, datetime.utcnow())
    await db._conn.commit()
    await ctx.reply(
        f"✅ Đã kết chuyến: {trip.name}\n"
        "Gõ /chiaai để xem đề xuất chia tiền cuối cùng."
    )


async def _handle_trip_archive(ctx: RequestContext) -> None:
    db = get_db()
    trip = await TripRepository(db).get_by_id(ctx.trip_id)
    if not trip:
        await ctx.reply("Không tìm thấy chuyến.")
        return
    await TripRepository(db).set_archived(ctx.trip_id, datetime.utcnow())
    await db._conn.commit()
    await ctx.reply(f"📦 Đã lưu trữ chuyến: {trip.name}")


async def _handle_pause_bot(ctx: RequestContext) -> None:
    if ctx.member_id not in get_settings().admin_member_id_list:
        await ctx.reply("⛔ Lệnh này chỉ dành cho admin.")
        return
    db = get_db()
    await db.set_setting("bot_enabled", "false")
    await db._conn.commit()
    await ctx.reply("⏸ Bot đã tạm dừng. Gõ /resume_bot để bật lại.")


async def _handle_resume_bot(ctx: RequestContext) -> None:
    if ctx.member_id not in get_settings().admin_member_id_list:
        await ctx.reply("⛔ Lệnh này chỉ dành cho admin.")
        return
    db = get_db()
    await db.set_setting("bot_enabled", "true")
    await db._conn.commit()
    await ctx.reply("▶️ Bot đã hoạt động trở lại.")


async def _handle_huy_auto_advance(ctx: RequestContext, expense_id: str) -> None:
    """Huỷ auto-advance contribution gắn với expense."""
    if not expense_id:
        await ctx.reply("Dùng: /huy_auto <expense_id>")
        return
    from app.storage.repositories.expense_repo import ContributionRepository
    from app.domain.models import ContributionKind

    db = get_db()
    contrib_repo = ContributionRepository(db)
    all_contribs = await contrib_repo.list_active(ctx.trip_id)
    auto = next(
        (c for c in all_contribs
         if c.linked_expense_id == expense_id
         and c.kind == ContributionKind.AUTO_ADVANCE),
        None,
    )
    if not auto:
        await ctx.reply(f"Không tìm thấy auto-advance cho expense '{expense_id}'.")
        return
    await contrib_repo.cancel(ctx.trip_id, auto.id)
    from app.storage.repositories.expense_repo import ExpenseRepository
    await ExpenseRepository(db).cancel(ctx.trip_id, expense_id)
    from app.storage.repositories import AuditLogRepository
    await AuditLogRepository(db).insert(
        action="huy_auto_advance",
        trip_id=ctx.trip_id,
        actor_id=ctx.member_id,
        entity_id=expense_id,
        trace_id=ctx.trace_id,
    )
    await db._conn.commit()
    await ctx.reply(f"✅ Đã huỷ auto-advance và expense '{expense_id}'.")


async def _handle_rebuild_sheet(ctx: RequestContext) -> None:
    if ctx.member_id not in get_settings().admin_member_id_list:
        trip = await TripRepository(get_db()).get_by_id(ctx.trip_id)
        if not trip or trip.created_by != ctx.member_id:
            await ctx.reply("⛔ Lệnh này chỉ dành cho admin.")
            return
    from app.tools.sheets import rebuild_sheet_from_db
    from app.storage.repositories.expense_repo import ExpenseRepository, ContributionRepository
    db = get_db()
    trip = await TripRepository(db).get_by_id(ctx.trip_id)
    sheet_id = trip.sheet_id if trip else None
    if not sheet_id:
        await ctx.reply("⚠️ Chuyến này chưa có Google Sheet.")
        return
    expenses = [e.__dict__ for e in await ExpenseRepository(db).list_active(ctx.trip_id)]
    contribs = [c.__dict__ for c in await ContributionRepository(db).list_active(ctx.trip_id)]
    await rebuild_sheet_from_db(sheet_id, ctx.trip_id, expenses, contribs)
    await ctx.reply("✅ Đã gửi lệnh rebuild sheet vào queue.")


# Avoid circular import
from datetime import timedelta
