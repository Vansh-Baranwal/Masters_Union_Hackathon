"""
Trust assessment, machine-observed states, case logic, adaptive evidence challenge.

Spec §6, §9, §12:

Evidence levels (per attribute, never global):
  extracted            — field successfully extracted
  corroborated         — two independent sources agree on attribute
  independently_verified — authoritative external source confirmed it

Machine states (never assertions):
  payment_seen, ticket_seen, linked_exact, linked_inferred,
  case_opened, refund_evidence_seen

Human assertions (stored separately as Decisions):
  traveller_asserts_travel
  coordinator: approved | rejected | proof_requested

Adaptive challenge: asks for the smallest extra item that would conflict
with a weak claim, names the unresolved check. Never auto-rejects.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.models import DBInterpretation, DBRelationship, DBDecision, DBCase
from core.store import Store

import structlog

log = structlog.get_logger(__name__)


class EvidenceLevel(str, Enum):
    EXTRACTED = "extracted"
    CORROBORATED = "corroborated"
    INDEPENDENTLY_VERIFIED = "independently_verified"
    NOT_PRESENT = "not_present"


class MachineState(str, Enum):
    PAYMENT_SEEN = "payment_seen"
    TICKET_SEEN = "ticket_seen"
    LINKED_EXACT = "linked_exact"
    LINKED_INFERRED = "linked_inferred"
    CASE_OPENED = "case_opened"
    REFUND_EVIDENCE_SEEN = "refund_evidence_seen"


PAYMENT_TYPES = {"UPI_SUCCESS", "BANK_SMS"}
TICKET_TYPES  = {"TICKET_QR"}
REFUND_TYPES  = {"REFUND_NOTICE"}
FAILURE_TYPES = {"UPI_FAILED_PENDING", "BOT_ERROR"}


@dataclass
class TrustAssessment:
    evidence_id: str
    machine_states: list[str]
    # per-attribute evidence levels
    attribute_levels: dict[str, str]
    # human-readable verdict (never "fraud" or "verified")
    verdict: str
    # one-line reason suitable for display / reply card
    reason: str
    # whether an adaptive challenge should be triggered
    needs_challenge: bool
    challenge_message: Optional[str]
    # overall level for display — lowest of relevant attributes
    overall_level: EvidenceLevel

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "machine_states": self.machine_states,
            "attribute_levels": self.attribute_levels,
            "verdict": self.verdict,
            "reason": self.reason,
            "needs_challenge": self.needs_challenge,
            "challenge_message": self.challenge_message,
            "overall_level": self.overall_level.value,
        }


# ─── Challenge templates ───────────────────────────────────────────────────── #

CHALLENGE_TEMPLATES: dict[str, str] = {
    "utr_missing": (
        "We could not read the UTR (transaction reference) from your screenshot. "
        "Could you send your bank SMS for this payment or a screenshot of your payment-app history? "
        "If you cannot, the payment will be noted as 'corroborated, unverified' for the coordinator."
    ),
    "no_second_source": (
        "We found a payment record but no linked ticket. "
        "Please send the ticket screenshot or QR image you received from the metro app. "
        "If you do not have one, your case will be flagged for the coordinator."
    ),
    "timestamp_mismatch": (
        "The timestamps on your payment and ticket screenshots do not match within the expected window. "
        "Please send the original (not a cropped or forwarded) version of both screenshots."
    ),
    "amount_mismatch": (
        "The amounts on the linked records do not match. "
        "Please send a bank SMS or statement showing the exact debit amount for this journey."
    ),
    "suspect_pattern": (
        "This message matches patterns seen in refund scams. "
        "Do not click any links or share your OTP or PIN. "
        "If you believe this is a genuine refund notice, please forward the original SMS from your bank."
    ),
    "generic": (
        "We need one more piece of evidence to support your claim. "
        "Please send your bank debit SMS, payment-app history, or the metro ticket screenshot."
    ),
}


def _pick_challenge(unresolved_checks: list[str]) -> str:
    for check in unresolved_checks:
        if check in CHALLENGE_TEMPLATES:
            return CHALLENGE_TEMPLATES[check]
    return CHALLENGE_TEMPLATES["generic"]


# ─── Main assessor ────────────────────────────────────────────────────────── #

async def assess_trust(
    session: AsyncSession,
    store: Store,
    evidence_id: str,
    interp: DBInterpretation,
    relationships: list[DBRelationship],
    decisions: list[DBDecision],
) -> TrustAssessment:
    """
    Compute a TrustAssessment for one evidence item.
    Pure function over the provided records — no side effects.
    """
    screenshot_type = interp.screenshot_type
    fields = json.loads(interp.fields_json) if interp.fields_json else {}
    fc = json.loads(interp.field_confidence) if interp.field_confidence else {}

    machine_states: list[str] = []
    attribute_levels: dict[str, str] = {}
    unresolved_checks: list[str] = []

    # ── Determine machine states ──────────────────────────────────────────── #
    if screenshot_type in PAYMENT_TYPES:
        machine_states.append(MachineState.PAYMENT_SEEN.value)
    if screenshot_type in TICKET_TYPES:
        machine_states.append(MachineState.TICKET_SEEN.value)
    if screenshot_type in REFUND_TYPES:
        machine_states.append(MachineState.REFUND_EVIDENCE_SEEN.value)

    has_exact = any(r.type == "EXACT" for r in relationships)
    has_inferred = any(r.type == "INFERRED" for r in relationships)
    if has_exact:
        machine_states.append(MachineState.LINKED_EXACT.value)
    elif has_inferred:
        machine_states.append(MachineState.LINKED_INFERRED.value)

    open_cases = [d for d in decisions if d.action == "proof_requested"]
    if open_cases:
        machine_states.append(MachineState.CASE_OPENED.value)

    # ── Per-attribute evidence levels ─────────────────────────────────────── #
    # For tickets, the key attributes are ticket_id, timestamp, fare.
    # For payments, they are amount, timestamp, utr.
    # Use type_confidence as a floor when field-level confidence is 0
    # (happens when extract returned nothing but parse OCR got the value).
    type_conf = interp.type_confidence
    for attr in ("amount", "timestamp", "utr", "ticket_id", "order_id", "fare"):
        val = fields.get(attr)
        conf = fc.get(attr, 0.0)
        # If the field has a value but confidence is 0 (extract missed it, parse got it),
        # use the type confidence as a proxy — the value came from real OCR.
        if val is not None and conf == 0.0:
            conf = type_conf
        if val is None:
            attribute_levels[attr] = EvidenceLevel.NOT_PRESENT.value
        elif has_exact and attr in ("utr", "ticket_id", "order_id"):
            attribute_levels[attr] = EvidenceLevel.CORROBORATED.value
        elif conf >= 0.5:
            attribute_levels[attr] = EvidenceLevel.EXTRACTED.value
        else:
            attribute_levels[attr] = EvidenceLevel.NOT_PRESENT.value

    # ── UTR check ─────────────────────────────────────────────────────────── #
    utr = fields.get("utr")
    if screenshot_type in PAYMENT_TYPES and not utr:
        unresolved_checks.append("utr_missing")

    # ── Payment↔Ticket link check ─────────────────────────────────────────── #
    if screenshot_type in PAYMENT_TYPES and not has_exact and not has_inferred:
        unresolved_checks.append("no_second_source")

    # ── Suspect notice ────────────────────────────────────────────────────── #
    if screenshot_type == "SUSPECT_NOTICE":
        unresolved_checks.append("suspect_pattern")

    # ── Overall level ─────────────────────────────────────────────────────── #
    # Only consider attributes that are actually present for this screenshot type
    type_primary_attrs = {
        "TICKET_QR":          {"ticket_id", "timestamp", "fare"},
        "UPI_SUCCESS":        {"amount", "timestamp", "utr"},
        "BANK_SMS":           {"amount", "timestamp", "utr"},
        "UPI_FAILED_PENDING": {"amount", "timestamp"},
        "REFUND_NOTICE":      {"amount", "timestamp"},
        "BOT_ERROR":          {"timestamp"},
        "CLAIM_SUBMISSION":   {"ticket_id", "amount"},
    }
    primary = type_primary_attrs.get(screenshot_type, set(attribute_levels.keys()))
    level_order = {
        EvidenceLevel.NOT_PRESENT.value: 0,
        EvidenceLevel.EXTRACTED.value: 1,
        EvidenceLevel.CORROBORATED.value: 2,
        EvidenceLevel.INDEPENDENTLY_VERIFIED.value: 3,
    }
    # Only consider primary attributes that are present
    relevant_levels = [
        v for k, v in attribute_levels.items()
        if k in primary and v != EvidenceLevel.NOT_PRESENT.value
    ]
    if relevant_levels:
        overall_key = min(relevant_levels, key=lambda x: level_order.get(x, 0))
        overall_level = EvidenceLevel(overall_key)
    else:
        # Fall back to all attributes if none of the primary ones are present
        all_present = [v for v in attribute_levels.values() if v != EvidenceLevel.NOT_PRESENT.value]
        if all_present:
            overall_key = min(all_present, key=lambda x: level_order.get(x, 0))
            overall_level = EvidenceLevel(overall_key)
        else:
            overall_level = EvidenceLevel.NOT_PRESENT

    # ── Verdict string (spec §6: never "fraud", never "verified") ─────────── #
    if screenshot_type == "SUSPECT_NOTICE":
        verdict = "needs_review"
        reason = "Screenshot matches scam-message patterns. Do not act on it without verifying with your bank."
    elif screenshot_type == "OTHER" or interp.type_confidence < 0.5:
        verdict = "unreadable"
        reason = "Could not classify screenshot. Please resend a clearer image."
    elif MachineState.LINKED_EXACT.value in machine_states:
        verdict = "corroborated"
        reason = "Payment and ticket linked by shared identifier."
    elif MachineState.LINKED_INFERRED.value in machine_states:
        verdict = "corroborated"
        reason = "Payment and ticket linked by contextual match (requires coordinator review)."
    elif unresolved_checks:
        verdict = "needs_review"
        reason = f"Unresolved: {', '.join(unresolved_checks)}."
    else:
        verdict = "extracted"
        reason = f"Screenshot classified as {screenshot_type} with confidence {interp.type_confidence:.0%}."

    # ── Adaptive challenge ────────────────────────────────────────────────── #
    needs_challenge = bool(unresolved_checks) and verdict == "needs_review"
    challenge_message = _pick_challenge(unresolved_checks) if needs_challenge else None

    return TrustAssessment(
        evidence_id=evidence_id,
        machine_states=machine_states,
        attribute_levels=attribute_levels,
        verdict=verdict,
        reason=reason,
        needs_challenge=needs_challenge,
        challenge_message=challenge_message,
        overall_level=overall_level,
    )


async def open_case_if_needed(
    store: Store,
    assessment: TrustAssessment,
    trip_id: str,
    sender_id: str,
) -> Optional[DBCase]:
    """Open a case in the store if assessment says needs_review and no case exists yet."""
    if assessment.verdict != "needs_review":
        return None
    existing = await store.get_case_by_evidence(assessment.evidence_id)
    if existing:
        return existing
    case = await store.open_case(
        trip_id=trip_id,
        evidence_id=assessment.evidence_id,
        sender_id=sender_id,
        reason=assessment.reason,
    )
    log.info("case_opened_by_trust", case_id=case.case_id, evidence_id=assessment.evidence_id)
    return case
