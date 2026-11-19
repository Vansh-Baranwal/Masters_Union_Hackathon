"""
Telegram bot channel for Pratibimb.

Flow per incoming photo/document:
  1. Identify sender; look up trip from join code (if previously registered) or ask.
  2. Run full ingest pipeline (evidence → extraction → duplicate → link → trust).
  3. Optionally translate the reason via Sarvam.
  4. Generate reply card PNG and send it back.
  5. If challenge needed, send challenge message as plain text after the card.

Commands:
  /start              — welcome message
  /join <CODE>        — register sender under a trip join code
  /status             — show latest status for the sender's last submission
  /language <code>    — set preferred language (en / hi / kn)
  /help               — usage guide
"""
from __future__ import annotations

import io
import json
import logging
import os
from typing import Optional

from telegram import (
    Update,
    InputFile,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from core.database import init_db, get_session
from core.store import Store
from core.duplicates import detect_duplicates
from core.linking import propose_links
from core.trust import assess_trust, open_case_if_needed
from extraction.pipeline import run_extraction_pipeline
from extraction.sarvam_client import SarvamClient
from intake.processor import build_evidence_record
from cards.generator import generate_reply_card

log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# In-memory session: maps telegram chat_id → {trip_id, language_pref}
# Production: persist in DB (DBTraveller.language_pref)
_sessions: dict[int, dict] = {}

LANG_MAP = {"en": "en", "hi": "hi-IN", "kn": "kn-IN", "kn-in": "kn-IN", "hi-in": "hi-IN"}

WELCOME = (
    "👋 Welcome to *Pratibimb*.\n\n"
    "Send me any screenshot from your metro journey — ticket, payment, bank SMS, refund, or error — "
    "and I will file it, label it, and link it to your trip.\n\n"
    "To join a trip, send: `/join TRIPCODE`\n"
    "To set your language, send: `/language kn` (Kannada) or `/language hi` (Hindi)\n"
    "Type `/help` for more."
)

HELP = (
    "*Pratibimb commands*\n\n"
    "`/join CODE`  — join a trip using the 8-character code from your coordinator\n"
    "`/status`     — see the latest status of your last submission\n"
    "`/language CODE` — set reply language: `en`, `hi`, `kn`\n"
    "`/help`       — this message\n\n"
    "*To submit a screenshot:* just send the photo directly in this chat.\n\n"
    "_Every screenshot is filed as immutable evidence. "
    "Nothing is deleted or changed once submitted._"
)


# ─── Helpers ──────────────────────────────────────────────────────────────── #

def _get_session(chat_id: int) -> dict:
    if chat_id not in _sessions:
        _sessions[chat_id] = {"trip_id": None, "language_pref": "en", "last_evidence_id": None}
    return _sessions[chat_id]


def _lang(chat_id: int) -> str:
    return _get_session(chat_id).get("language_pref", "en")


async def _translate_reason(reason: str, lang: str) -> str:
    if lang == "en":
        return reason
    try:
        async with SarvamClient() as client:
            return await client.translate(reason, target_language_code=lang, source_language_code="en")
    except Exception:
        return reason


# ─── Command handlers ─────────────────────────────────────────────────────── #

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP, parse_mode="Markdown")


async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: `/join TRIPCODE`", parse_mode="Markdown")
        return

    join_code = args[0].strip().upper()
    async with get_session() as db_session:
        store = Store(db_session)
        trip = await store.get_trip_by_join_code(join_code)
        if not trip:
            await update.message.reply_text(
                f"❌ Join code `{join_code}` not found. Ask your coordinator for the correct code.",
                parse_mode="Markdown",
            )
            return
        sender_id = str(chat_id)
        await store.add_traveller(
            trip_id=trip.trip_id,
            sender_id=sender_id,
            display_name=update.effective_user.full_name if update.effective_user else None,
            language_pref=_lang(chat_id),
        )
        sess = _get_session(chat_id)
        sess["trip_id"] = trip.trip_id

    await update.message.reply_text(
        f"✅ Joined trip *{trip.name}*.\nNow send your screenshots and I will file them.",
        parse_mode="Markdown",
    )


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: `/language en|hi|kn`", parse_mode="Markdown")
        return
    code = LANG_MAP.get(args[0].lower().strip(), "en")
    _get_session(chat_id)["language_pref"] = code
    await update.message.reply_text(f"Language set to `{code}`.", parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    sess = _get_session(chat_id)
    ev_id = sess.get("last_evidence_id")
    if not ev_id:
        await update.message.reply_text("No recent submission found. Send a screenshot first.")
        return
    async with get_session() as db_session:
        store = Store(db_session)
        interp = await store.get_latest_interpretation(ev_id)
        if not interp:
            await update.message.reply_text("Still processing — please wait a moment.")
            return
        rels = await store.get_relationships_for(ev_id)
        decs = await store.get_decisions_for(ev_id)
        assessment = await assess_trust(
            session=db_session, store=store, evidence_id=ev_id,
            interp=interp, relationships=rels, decisions=decs,
        )
    lang = _lang(chat_id)
    translated = await _translate_reason(assessment.reason, lang)
    await update.message.reply_text(
        f"*Status:* {assessment.verdict}\n{translated}",
        parse_mode="Markdown",
    )


# ─── Photo handler ────────────────────────────────────────────────────────── #

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    sess = _get_session(chat_id)
    lang = sess.get("language_pref", "en")

    # Acknowledge receipt immediately (Sarvam jobs are async)
    ack = await update.message.reply_text("📥 Received — filing your screenshot…")

    # Download image bytes
    if update.message.photo:
        file_obj = await context.bot.get_file(update.message.photo[-1].file_id)
    elif update.message.document and update.message.document.mime_type.startswith("image/"):
        file_obj = await context.bot.get_file(update.message.document.file_id)
    else:
        await ack.edit_text("Please send an image or photo.")
        return

    image_bytes = await file_obj.download_as_bytearray()
    image_bytes = bytes(image_bytes)

    sender_id = str(chat_id)
    trip_id = sess.get("trip_id")

    async with get_session() as db_session:
        store = Store(db_session)

        # 1. Build & save evidence
        ev_record, _ = build_evidence_record(image_bytes, sender_id, "telegram", trip_id)
        await store.add_evidence(ev_record)
        sess["last_evidence_id"] = ev_record.evidence_id

        # 2. Extract
        interp_record = await run_extraction_pipeline(image_bytes, ev_record.evidence_id)
        db_interp = await store.add_interpretation(interp_record)
        db_ev = await store.get_evidence(ev_record.evidence_id)

        # 3. Duplicates
        dup_result = await detect_duplicates(db_session, db_ev, db_interp, trip_id)

        # 4. Link
        proposals = await propose_links(db_session, ev_record.evidence_id, db_interp, trip_id, dup_result)
        for p in proposals:
            to_id = p.to_id or ev_record.evidence_id
            await store.add_relationship(
                from_id=p.from_id, to_id=to_id, rel_type=p.rel_type,
                basis=p.basis, score=p.score, created_by="system",
                plain_reason=p.plain_reason,
            )

        # 5. Trust
        rels = await store.get_relationships_for(ev_record.evidence_id)
        decs = await store.get_decisions_for(ev_record.evidence_id)
        assessment = await assess_trust(
            session=db_session, store=store, evidence_id=ev_record.evidence_id,
            interp=db_interp, relationships=rels, decisions=decs,
        )

        # 6. Open case if needed
        if trip_id:
            await open_case_if_needed(store, assessment, trip_id, sender_id)

    # 7. Translate reason
    translated_reason = await _translate_reason(assessment.reason, lang)

    # 8. Build fields for card
    fields = {}
    if interp_record.fields:
        fields = interp_record.fields.model_dump()

    strongest_rel: Optional[str] = None
    if proposals:
        strongest_rel = max(proposals, key=lambda p: p.score).rel_type

    # 9. Generate card
    card_bytes = generate_reply_card(
        assessment_verdict=assessment.verdict,
        screenshot_type=interp_record.screenshot_type.value,
        reason=assessment.reason,
        lang=lang,
        amount=fields.get("amount"),
        currency=fields.get("currency", "INR"),
        origin_station=fields.get("origin_station"),
        destination_station=fields.get("destination_station"),
        relationship_type=strongest_rel,
        evidence_level=assessment.overall_level.value,
        evidence_id_short=ev_record.evidence_id[:8],
        dynamic_reason_translated=translated_reason,
    )

    # 10. Send card
    await ack.delete()
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=InputFile(io.BytesIO(card_bytes), filename="pratibimb_card.png"),
        caption=f"Ref: `{ev_record.evidence_id[:8]}`",
        parse_mode="Markdown",
    )

    # 11. Send challenge if needed
    if assessment.needs_challenge and assessment.challenge_message:
        challenge_text = await _translate_reason(assessment.challenge_message, lang)
        await context.bot.send_message(chat_id=chat_id, text=f"ℹ️ {challenge_text}")

    # 12. Duplicate warning
    if dup_result and dup_result.has_duplicates:
        strongest = dup_result.strongest
        warn = (
            f"⚠️ This screenshot matches a previous submission "
            f"({strongest.kind.value}, ref: {strongest.evidence_id[:8]})."
        )
        await context.bot.send_message(chat_id=chat_id, text=warn)


# ─── Application builder ──────────────────────────────────────────────────── #

def build_application() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in environment.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("join", cmd_join))
    app.add_handler(CommandHandler("language", cmd_language))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))

    return app


def run_bot_sync() -> None:
    """
    Synchronous entry point — called from main.py via a plain function call.
    python-telegram-bot v20+ manages its own event loop internally;
    we must NOT wrap run_polling() inside asyncio.run().
    """
    import asyncio as _asyncio
    _asyncio.run(init_db())
    application = build_application()
    log.info("Starting Pratibimb Telegram bot…")
    # run_polling() blocks until the process is interrupted.
    application.run_polling(allowed_updates=Update.ALL_TYPES)


async def run_bot() -> None:
    """Async shim kept for compatibility — delegates to sync runner."""
    import asyncio as _asyncio
    loop = _asyncio.get_event_loop()
    await loop.run_in_executor(None, run_bot_sync)
