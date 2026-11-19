"""
Reply-card generator.

Produces a PNG image card for each verdict type:
  - ticket_received   (green)
  - payment_found     (amber — payment seen, no ticket)
  - corroborated      (blue — linked)
  - extracted         (grey — recorded, no link yet)
  - needs_review      (orange — exception, coordinator notified)
  - unreadable        (red — could not classify)

Cards are intentionally simple so users can screenshot them and re-share.
No personal data beyond masked fields is embedded in the image.
"""
from __future__ import annotations

import io
from enum import Enum
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from cards.translations import get_string

# ── Palette ────────────────────────────────────────────────────────────────── #
PALETTE = {
    "ticket_received": {"bg": "#1A7A4A", "header": "#145C38", "text": "#FFFFFF", "accent": "#A8F0C6"},
    "payment_found":   {"bg": "#C47C00", "header": "#9A6000", "text": "#FFFFFF", "accent": "#FFE08A"},
    "corroborated":    {"bg": "#1B5E9E", "header": "#144A80", "text": "#FFFFFF", "accent": "#90CAF9"},
    "extracted":       {"bg": "#424242", "header": "#303030", "text": "#FFFFFF", "accent": "#BDBDBD"},
    "needs_review":    {"bg": "#C84B00", "header": "#A03C00", "text": "#FFFFFF", "accent": "#FFB74D"},
    "unreadable":      {"bg": "#B71C1C", "header": "#7F1414", "text": "#FFFFFF", "accent": "#EF9A9A"},
}

CARD_W, CARD_H = 540, 300
HEADER_H = 72
PADDING = 20
FOOTER_H = 44

# ── Verdict enum ───────────────────────────────────────────────────────────── #

class CardVerdict(str, Enum):
    TICKET_RECEIVED = "ticket_received"
    PAYMENT_FOUND   = "payment_found"
    CORROBORATED    = "corroborated"
    EXTRACTED       = "extracted"
    NEEDS_REVIEW    = "needs_review"
    UNREADABLE      = "unreadable"


VERDICT_FOR_ASSESSMENT = {
    "extracted":    CardVerdict.EXTRACTED,
    "corroborated": CardVerdict.CORROBORATED,
    "needs_review": CardVerdict.NEEDS_REVIEW,
    "unreadable":   CardVerdict.UNREADABLE,
}

SCREENSHOT_TO_VERDICT = {
    "TICKET_QR":          CardVerdict.TICKET_RECEIVED,
    "UPI_SUCCESS":        CardVerdict.PAYMENT_FOUND,
    "UPI_FAILED_PENDING": CardVerdict.NEEDS_REVIEW,
    "BANK_SMS":           CardVerdict.PAYMENT_FOUND,
    "REFUND_NOTICE":      CardVerdict.EXTRACTED,
    "BOT_ERROR":          CardVerdict.NEEDS_REVIEW,
    "CLAIM_SUBMISSION":   CardVerdict.EXTRACTED,
    "SUSPECT_NOTICE":     CardVerdict.NEEDS_REVIEW,
    "OTHER":              CardVerdict.UNREADABLE,
}


def _resolve_verdict(assessment_verdict: str, screenshot_type: str, has_link: bool) -> CardVerdict:
    """Pick the most informative card verdict given the assessment outcome."""
    if assessment_verdict == "unreadable":
        return CardVerdict.UNREADABLE
    if assessment_verdict == "needs_review":
        return CardVerdict.NEEDS_REVIEW
    if assessment_verdict == "corroborated" or has_link:
        return CardVerdict.CORROBORATED
    # Fall back to screenshot-type mapping
    return SCREENSHOT_TO_VERDICT.get(screenshot_type, CardVerdict.EXTRACTED)


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Try to load a system font; fall back to PIL default."""
    font_paths = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _draw_rounded_rect(draw: ImageDraw.Draw, xy, radius: int, fill: str) -> None:
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)


def generate_reply_card(
    assessment_verdict: str,
    screenshot_type: str,
    reason: str,
    lang: str = "en",
    amount: Optional[float] = None,
    currency: str = "INR",
    origin_station: Optional[str] = None,
    destination_station: Optional[str] = None,
    relationship_type: Optional[str] = None,
    evidence_level: Optional[str] = None,
    evidence_id_short: Optional[str] = None,
    dynamic_reason_translated: Optional[str] = None,
) -> bytes:
    """
    Render a reply card and return PNG bytes.

    Parameters
    ----------
    assessment_verdict   : one of extracted / corroborated / needs_review / unreadable
    screenshot_type      : TICKET_QR | UPI_SUCCESS | … (ScreenshotType value)
    reason               : English reason string (translated version passed separately)
    lang                 : BCP-47 code for card text language
    dynamic_reason_translated : pre-translated reason string (from SarvamClient.translate)
    """
    has_link = relationship_type in ("EXACT", "INFERRED", "MANUAL")
    verdict = _resolve_verdict(assessment_verdict, screenshot_type, has_link)
    colors = PALETTE[verdict.value]

    img = Image.new("RGB", (CARD_W, CARD_H), color=colors["bg"])
    draw = ImageDraw.Draw(img)

    font_lg = _load_font(22, bold=True)
    font_md = _load_font(16, bold=False)
    font_sm = _load_font(13, bold=False)
    font_xs = _load_font(11, bold=False)

    # ── Header band ───────────────────────────────────────────────────────── #
    _draw_rounded_rect(draw, [0, 0, CARD_W, HEADER_H], radius=0, fill=colors["header"])

    app_name = get_string("app_name", lang)
    header_label = get_string(verdict.value, lang)
    draw.text((PADDING, 14), app_name, font=font_sm, fill=colors["accent"])
    draw.text((PADDING, 34), header_label, font=font_lg, fill=colors["text"])

    # ── Body ──────────────────────────────────────────────────────────────── #
    y = HEADER_H + PADDING

    # Amount + route row
    if amount is not None:
        sym = "₹" if currency == "INR" else currency
        amt_str = f"{sym}{amount:,.2f}"
        draw.text((PADDING, y), f"{get_string('label_amount', lang)}: {amt_str}", font=font_md, fill=colors["text"])
        y += 26

    if origin_station or destination_station:
        route = f"{origin_station or '?'}  →  {destination_station or '?'}"
        draw.text((PADDING, y), route, font=font_md, fill=colors["text"])
        y += 26

    # Evidence & relationship
    if evidence_level:
        draw.text(
            (PADDING, y),
            f"{get_string('label_evidence', lang)}: {evidence_level}",
            font=font_sm, fill=colors["accent"],
        )
        y += 20

    if relationship_type:
        draw.text(
            (PADDING, y),
            f"{get_string('label_link', lang)}: {relationship_type}",
            font=font_sm, fill=colors["accent"],
        )
        y += 20

    # Reason
    display_reason = dynamic_reason_translated or reason
    # Word-wrap at ~60 chars
    words = display_reason.split()
    lines, line = [], []
    for w in words:
        line.append(w)
        if len(" ".join(line)) > 60:
            lines.append(" ".join(line[:-1]))
            line = [w]
    if line:
        lines.append(" ".join(line))

    y = max(y, HEADER_H + PADDING + 80)  # keep reason below mid-card
    for ln in lines[:3]:
        draw.text((PADDING, y), ln, font=font_sm, fill=colors["text"])
        y += 18

    # Ref
    if evidence_id_short:
        draw.text(
            (PADDING, CARD_H - FOOTER_H - 16),
            f"{get_string('label_ref', lang)}: {evidence_id_short}",
            font=font_xs, fill=colors["accent"],
        )

    # ── Footer ────────────────────────────────────────────────────────────── #
    _draw_rounded_rect(draw, [0, CARD_H - FOOTER_H, CARD_W, CARD_H], radius=0, fill=colors["header"])
    draw.text(
        (PADDING, CARD_H - FOOTER_H + 6),
        get_string("footer_note", lang),
        font=font_xs, fill=colors["accent"],
    )
    draw.text(
        (PADDING, CARD_H - FOOTER_H + 22),
        get_string("footer_caution", lang),
        font=font_xs, fill=colors["text"],
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()
