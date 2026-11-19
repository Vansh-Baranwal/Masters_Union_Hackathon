"""
Linking engine (spec §9):

Relationship types
  EXACT    — shared transaction or ticket identifier; eligible for auto-clear
  INFERRED — amount + timestamp + payer + journey context agree; always reviewed
  MANUAL   — coordinator explicitly linked; recorded as a Decision
  UNMATCHED — insufficient evidence; both candidates preserved and shown

Rules:
  - Ambiguity (two plausible matches) → UNMATCHED with both candidates listed.
  - Never force a guess.
  - Only deterministic code decides the relationship type; model output is input data.
  - Every relationship is written via store.add_relationship (append-only).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import DBEvidence, DBInterpretation, DBRelationship
from core.duplicates import DuplicateResult, DuplicateKind

import structlog

log = structlog.get_logger(__name__)

TIME_TOLERANCE_SECONDS = int(os.getenv("INFERRED_LINK_TIME_TOLERANCE_SECONDS", "600"))
INFERRED_MIN_SCORE = float(os.getenv("INFERRED_LINK_MIN_SCORE", "0.55"))

PAYMENT_TYPES = {"UPI_SUCCESS", "BANK_SMS", "UPI_FAILED_PENDING"}
TICKET_TYPES  = {"TICKET_QR"}
REFUND_TYPES  = {"REFUND_NOTICE"}


@dataclass
class LinkProposal:
    from_id: str
    to_id: str
    rel_type: str           # EXACT | INFERRED | UNMATCHED
    basis: list[str]
    score: float
    plain_reason: str


def _parse_fields(interp: DBInterpretation) -> dict:
    if not interp or not interp.fields_json:
        return {}
    try:
        return json.loads(interp.fields_json)
    except Exception:
        return {}


def _ts_seconds(ts_str: Optional[str]) -> Optional[float]:
    if not ts_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(ts_str, fmt)
            return dt.timestamp()
        except ValueError:
            continue
    return None


def _shared_identifiers(fa: dict, fb: dict) -> list[str]:
    matched = []
    for key in ("utr", "order_id", "ticket_id", "qr_payload"):
        va = fa.get(key)
        vb = fb.get(key)
        if va and vb and str(va).strip() == str(vb).strip():
            matched.append(key)
    return matched


def _inferred_score(fa: dict, fb: dict, type_a: str, type_b: str) -> tuple[float, list[str]]:
    """
    Score an INFERRED link on contextual attributes.
    Returns (score 0-1, basis list).
    """
    basis: list[str] = []
    score = 0.0

    # Amount match
    amt_a = fa.get("amount")
    amt_b = fb.get("amount")
    if amt_a and amt_b:
        try:
            if abs(float(amt_a) - float(amt_b)) < 0.01:
                basis.append("amount")
                score += 0.30
        except (ValueError, TypeError):
            pass

    # Timestamp proximity
    ts_a = _ts_seconds(fa.get("timestamp"))
    ts_b = _ts_seconds(fb.get("timestamp"))
    if ts_a and ts_b:
        delta = abs(ts_a - ts_b)
        if delta <= TIME_TOLERANCE_SECONDS:
            basis.append(f"timestamp_delta={int(delta)}s")
            score += 0.25

    # Station match
    if fa.get("origin_station") and fa.get("origin_station") == fb.get("origin_station"):
        basis.append("origin_station")
        score += 0.15
    if fa.get("destination_station") and fa.get("destination_station") == fb.get("destination_station"):
        basis.append("destination_station")
        score += 0.15

    # Payment↔Ticket pairing gets a boost
    types = {type_a, type_b}
    if PAYMENT_TYPES & types and TICKET_TYPES & types:
        basis.append("payment_ticket_pair")
        score += 0.15

    # Payer name match (masked – compare last 4 chars if available)
    payer_a = fa.get("payer_name_masked", "")
    payer_b = fb.get("payer_name_masked", "")
    if payer_a and payer_b and len(payer_a) >= 4 and payer_a[-4:] == payer_b[-4:]:
        basis.append("payer_suffix")
        score += 0.10

    return round(min(score, 1.0), 3), basis


# ─── Main linker ──────────────────────────────────────────────────────────── #

async def propose_links(
    session: AsyncSession,
    new_evidence_id: str,
    new_interp: Optional[DBInterpretation],
    trip_id: Optional[str],
    duplicate_result: Optional[DuplicateResult] = None,
) -> list[LinkProposal]:
    """
    Given a newly ingested evidence item, propose links to existing items.
    Returns a list of LinkProposals (may be empty; never raises on ambiguity).
    """
    proposals: list[LinkProposal] = []

    if not new_interp:
        return proposals

    new_fields = _parse_fields(new_interp)
    new_type = new_interp.screenshot_type

    # ── Fetch candidate evidence in the same trip ────────────────────────── #
    q = select(DBEvidence).where(
        DBEvidence.evidence_id != new_evidence_id,
        DBEvidence.trip_id == trip_id,
    )
    candidates = list((await session.execute(q)).scalars().all())

    if not candidates:
        return proposals

    exact_hits: list[LinkProposal] = []
    inferred_hits: list[LinkProposal] = []

    for ev in candidates:
        # Get latest interpretation
        interp_q = await session.execute(
            select(DBInterpretation)
            .where(DBInterpretation.evidence_id == ev.evidence_id)
            .order_by(DBInterpretation.created_at.desc())
            .limit(1)
        )
        ev_interp = interp_q.scalar_one_or_none()
        if not ev_interp:
            continue

        ev_fields = _parse_fields(ev_interp)
        ev_type = ev_interp.screenshot_type

        # ── EXACT: shared identifier ─────────────────────────────────────── #
        shared = _shared_identifiers(new_fields, ev_fields)
        if shared:
            exact_hits.append(LinkProposal(
                from_id=new_evidence_id,
                to_id=ev.evidence_id,
                rel_type="EXACT",
                basis=shared,
                score=1.0,
                plain_reason=f"Shared identifier(s): {', '.join(shared)}",
            ))
            continue  # don't also score INFERRED for the same pair

        # ── INFERRED: contextual attributes ─────────────────────────────── #
        inf_score, inf_basis = _inferred_score(new_fields, ev_fields, new_type, ev_type)
        if inf_score >= INFERRED_MIN_SCORE:
            inferred_hits.append(LinkProposal(
                from_id=new_evidence_id,
                to_id=ev.evidence_id,
                rel_type="INFERRED",
                basis=inf_basis,
                score=inf_score,
                plain_reason=f"Contextual match (score {inf_score}): {', '.join(inf_basis)}",
            ))

    # ── EXACT: take all (multiple exact matches are possible in group travel) #
    proposals.extend(exact_hits)

    # ── INFERRED: ambiguity guard ────────────────────────────────────────── #
    if len(inferred_hits) == 1:
        proposals.append(inferred_hits[0])
    elif len(inferred_hits) > 1:
        # Two or more plausible matches → UNMATCHED with candidates listed
        all_candidate_ids = [h.to_id for h in inferred_hits]
        proposals.append(LinkProposal(
            from_id=new_evidence_id,
            to_id="|".join(all_candidate_ids),
            rel_type="UNMATCHED",
            basis=["ambiguous_inferred"],
            score=max(h.score for h in inferred_hits),
            plain_reason=(
                f"Ambiguous: {len(inferred_hits)} plausible matches "
                f"({', '.join(all_candidate_ids[:3])}{'...' if len(all_candidate_ids) > 3 else ''}). "
                "Coordinator review required."
            ),
        ))

    # ── UNMATCHED: no link at all ─────────────────────────────────────────── #
    if not proposals:
        # Only generate an UNMATCHED record if there were candidates to compare against
        if candidates:
            proposals.append(LinkProposal(
                from_id=new_evidence_id,
                to_id="",
                rel_type="UNMATCHED",
                basis=["no_match"],
                score=0.0,
                plain_reason="No matching identifier or sufficient contextual evidence found.",
            ))

    for p in proposals:
        log.info(
            "link_proposed",
            from_id=p.from_id,
            to_id=p.to_id,
            type=p.rel_type,
            score=p.score,
            basis=p.basis,
        )

    return proposals
