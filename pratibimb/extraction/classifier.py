"""
Screenshot classifier for Pratibimb.

Two-pass approach (per spec §A5):
  Pass 1 — cheap keyword/layout rules on extracted text.
  Pass 2 — Sarvam-105B for ambiguous cases (async, called externally).

Returns: (ScreenshotType, confidence: float, reason: str)
Confidence threshold below which we return OTHER: CONFIDENCE_THRESHOLD.
"""
from __future__ import annotations

import re
from typing import Tuple

from intake.models import ScreenshotType

CONFIDENCE_THRESHOLD = 0.50  # Below this → OTHER with low_confidence flag


# ─── Keyword rule sets ────────────────────────────────────────────────────── #
# Each entry: (ScreenshotType, [must_match patterns], [must_not patterns], weight)
# Patterns are case-insensitive regex fragments applied to the raw OCR text.
_RULES: list[tuple[ScreenshotType, list[str], list[str], float]] = [
    # Ticket QR
    (
        ScreenshotType.TICKET_QR,
        [r"(ticket|booking)\s*(id|no|#)", r"(qr|scan|valid)", r"(indiranagar|mg road|majestic|baiyappanahalli|namma metro|bmrcl)"],
        [r"payment\s+fail", r"pending", r"refund"],
        0.85,
    ),
    # UPI Success
    (
        ScreenshotType.UPI_SUCCESS,
        [r"(paid|payment\s+successful|money\s+sent|₹.*sent|sent\s+successfully)", r"(upi|gpay|phonepe|paytm|bhim|google pay)"],
        [r"fail|pending|processing|could not"],
        0.88,
    ),
    # UPI Failed / Pending
    (
        ScreenshotType.UPI_FAILED_PENDING,
        [r"(payment\s+fail|transaction\s+fail|could not complete|pending|processing|money\s+debited.*ticket)"],
        [],
        0.82,
    ),
    # Bank SMS
    (
        ScreenshotType.BANK_SMS,
        [r"(debited|credited|a/c|acct|your account)", r"(hdfc|sbi|icici|axis|kotak|yes bank|bob|pnb|upi ref)"],
        [r"click here|download|install|kyc|otp to claim"],
        0.85,
    ),
    # Refund Notice
    (
        ScreenshotType.REFUND_NOTICE,
        [r"refund", r"(initiated|processed|credited|source)"],
        [r"click here to claim|download.*apk|scan.*qr.*refund"],
        0.80,
    ),
    # Bot Error
    (
        ScreenshotType.BOT_ERROR,
        [r"(booking failed|ticket.*not.*issued|could not.*book|try again|working days)", r"(namma metro|bmrcl|whatsapp)"],
        [],
        0.80,
    ),
    # Claim Submission
    (
        ScreenshotType.CLAIM_SUBMISSION,
        [r"(reimburs|claim|expense|submit.*ticket)", r"(employee|hr|admin|trip|journey)"],
        [],
        0.75,
    ),
    # Suspect Notice — must check BEFORE Refund
    (
        ScreenshotType.SUSPECT_NOTICE,
        [r"(click here|tap here).*(refund|claim|kyc|verify)", r"(anydesk|teamviewer|install.*apk|download.*link)", r"(otp|pin).*to\s+(claim|receive|get)\s+(refund|money)"],
        [],
        0.90,
    ),
]


def _score_rules(text: str) -> list[tuple[ScreenshotType, float, str]]:
    """
    Apply all rule sets to `text` (lowercased).
    Returns list of (type, confidence, matched_pattern) sorted descending by confidence.
    """
    t = text.lower()
    results = []
    for stype, must_match, must_not, weight in _RULES:
        # Fail-fast on exclusion patterns
        if any(re.search(p, t) for p in must_not):
            continue
        matched = [p for p in must_match if re.search(p, t)]
        if not matched:
            continue
        # Confidence scales with how many required patterns matched
        coverage = len(matched) / len(must_match) if must_match else 1.0
        confidence = round(weight * (0.6 + 0.4 * coverage), 3)
        results.append((stype, confidence, matched[0]))
    return sorted(results, key=lambda x: x[1], reverse=True)


def classify_screenshot(
    raw_text: str,
    qr_found: bool = False,
) -> Tuple[ScreenshotType, float, str]:
    """
    Rule-based classifier (Pass 1).
    Returns (ScreenshotType, confidence, reason).

    If confidence < CONFIDENCE_THRESHOLD the caller should escalate to
    Pass 2 (SarvamClient.classify_with_llm).
    """
    if not raw_text or not raw_text.strip():
        return ScreenshotType.OTHER, 0.0, "no text extracted"

    # QR presence alone bumps TICKET_QR if the text also hints at metro
    extra_text = " qr_found=true" if qr_found else ""
    text = raw_text + extra_text

    scores = _score_rules(text)

    if not scores:
        return ScreenshotType.OTHER, 0.0, "no rule matched"

    best_type, best_conf, best_pattern = scores[0]

    if best_conf < CONFIDENCE_THRESHOLD:
        return ScreenshotType.OTHER, best_conf, f"best match {best_type.value} below threshold (pattern: {best_pattern})"

    # Ambiguity guard: if top-two are within 0.05 of each other, reduce confidence
    if len(scores) > 1 and (scores[0][1] - scores[1][1]) < 0.05:
        best_conf = round(best_conf * 0.85, 3)
        reason = f"ambiguous ({best_type.value} vs {scores[1][0].value}); confidence reduced"
        if best_conf < CONFIDENCE_THRESHOLD:
            return ScreenshotType.OTHER, best_conf, reason
        return best_type, best_conf, reason

    return best_type, best_conf, f"matched rule: {best_pattern}"
