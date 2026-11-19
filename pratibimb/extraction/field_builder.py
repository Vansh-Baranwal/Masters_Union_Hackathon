"""
Field builder: takes raw Sarvam API output and QR decoded data, applies
normalisers, and returns a typed ExtractedFields + field_confidence dict.

Rule: every returned value must appear in raw text or be derivable from the
QR decoder. A null is correct. An invented value is a bug.
"""
from __future__ import annotations

from typing import Any, Optional

from intake.models import ExtractedFields
from intake.normalisers import (
    normalize_amount,
    normalize_timestamp,
    normalize_utr,
    normalize_order_or_ticket_id,
    mask_payer_name,
)


def _get(d: dict, *keys: str, default: Any = None) -> Any:
    """Try multiple keys; return first non-None value."""
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return default


def build_fields_from_sarvam(
    sarvam_fields: dict,
    raw_text: str = "",
    qr_parsed: Optional[dict] = None,
    base_confidence: float = 0.75,
) -> tuple[ExtractedFields, dict[str, float], dict[str, str], list[dict]]:
    """
    Merge Sarvam extracted fields with QR-parsed data and apply normalisers.

    Returns:
        fields          ExtractedFields (nulls valid)
        field_confidence  {field_name: 0.0–1.0}
        field_sources     {field_name: source_name}
        corrections       list of normaliser correction logs
    """
    fc: dict[str, float] = {}
    fs: dict[str, str] = {}
    corrections: list[dict] = []

    def conf(key: str, raw_val: Any, source: str, c: float = base_confidence) -> float:
        """Register confidence and source; return 0.0 if value is None."""
        if raw_val is None:
            fc[key] = 0.0
            fs[key] = source
            return 0.0
        fc[key] = round(c, 3)
        fs[key] = source
        return round(c, 3)

    # ── Amount ───────────────────────────────────────────────────────────── #
    raw_amount = _get(sarvam_fields, "amount", "fare", "total_amount")
    amount, currency = normalize_amount(raw_amount)
    conf("amount", amount, "sarvam_extract")
    conf("currency", currency, "sarvam_extract", 0.9)

    # ── Fare (may differ from amount on tickets) ──────────────────────────── #
    raw_fare = _get(sarvam_fields, "fare")
    fare, _ = normalize_amount(raw_fare)
    if fare is None and qr_parsed:
        fare = qr_parsed.get("fare")
        conf("fare", fare, "qr_decoder", 0.95)
    else:
        conf("fare", fare, "sarvam_extract")

    # ── Timestamp ─────────────────────────────────────────────────────────── #
    raw_ts = _get(sarvam_fields, "timestamp", "date", "time", "booking_time", "transaction_time")
    timestamp = normalize_timestamp(raw_ts)
    conf("timestamp", timestamp, "sarvam_extract")

    # ── UTR ───────────────────────────────────────────────────────────────── #
    raw_utr = _get(sarvam_fields, "utr", "upi_ref", "ref_no", "reference_number")
    utr, utr_corrections = normalize_utr(raw_utr)
    corrections.extend(utr_corrections)
    conf("utr", utr, "sarvam_extract", 0.85 if utr_corrections else base_confidence)

    # ── Order ID ──────────────────────────────────────────────────────────── #
    raw_order = _get(sarvam_fields, "order_id", "booking_id", "transaction_id", "merchant_ref")
    order_id, oid_corr = normalize_order_or_ticket_id(raw_order, "order_id")
    corrections.extend(oid_corr)
    # Try QR fallback
    if order_id is None and qr_parsed:
        order_id = qr_parsed.get("order_id") or qr_parsed.get("ticket_id")
        conf("order_id", order_id, "qr_decoder", 0.9)
    else:
        conf("order_id", order_id, "sarvam_extract")

    # ── Ticket ID ─────────────────────────────────────────────────────────── #
    raw_ticket = _get(sarvam_fields, "ticket_id", "ticket_number", "booking_ref")
    ticket_id, tid_corr = normalize_order_or_ticket_id(raw_ticket, "ticket_id")
    corrections.extend(tid_corr)
    if ticket_id is None and qr_parsed:
        ticket_id = qr_parsed.get("ticket_id")
        conf("ticket_id", ticket_id, "qr_decoder", 0.95)
    else:
        conf("ticket_id", ticket_id, "sarvam_extract")

    # ── QR payload ────────────────────────────────────────────────────────── #
    qr_payload = _get(sarvam_fields, "qr_payload")
    conf("qr_payload", qr_payload, "sarvam_extract", 0.7)

    # ── Stations ──────────────────────────────────────────────────────────── #
    origin = _get(sarvam_fields, "origin_station", "from_station", "source")
    if origin is None and qr_parsed:
        origin = qr_parsed.get("origin_station")
        conf("origin_station", origin, "qr_decoder", 0.9)
    else:
        conf("origin_station", origin, "sarvam_extract")

    dest = _get(sarvam_fields, "destination_station", "to_station", "destination")
    if dest is None and qr_parsed:
        dest = qr_parsed.get("destination_station")
        conf("destination_station", dest, "qr_decoder", 0.9)
    else:
        conf("destination_station", dest, "sarvam_extract")

    # ── Names ─────────────────────────────────────────────────────────────── #
    raw_payer = _get(sarvam_fields, "payer_name", "sender_name", "account_holder")
    payer_masked = mask_payer_name(raw_payer)
    conf("payer_name_masked", payer_masked, "sarvam_extract", 0.7)

    payee = _get(sarvam_fields, "payee_name", "merchant_name", "receiver_name")
    conf("payee_name", payee, "sarvam_extract")

    # ── Status text ───────────────────────────────────────────────────────── #
    status_text = _get(sarvam_fields, "status_text", "status", "message")
    conf("status_text", status_text, "sarvam_extract")

    # ── App & bank ────────────────────────────────────────────────────────── #
    app_name = _get(sarvam_fields, "app_name", "app", "platform")
    conf("app_name", app_name, "sarvam_extract")

    bank_name = _get(sarvam_fields, "bank_name", "bank")
    conf("bank_name", bank_name, "sarvam_extract")

    # ── Language ──────────────────────────────────────────────────────────── #
    language = _get(sarvam_fields, "language_detected", "language")
    conf("language_detected", language, "sarvam_extract", 0.8)

    fields = ExtractedFields(
        amount=amount,
        currency=currency or "INR",
        timestamp=timestamp,
        utr=utr,
        order_id=order_id,
        ticket_id=ticket_id,
        qr_payload=qr_payload,
        origin_station=origin,
        destination_station=dest,
        fare=fare,
        payer_name_masked=payer_masked,
        payee_name=payee,
        status_text=status_text,
        app_name=app_name,
        bank_name=bank_name,
        language_detected=language,
    )

    return fields, fc, fs, corrections
