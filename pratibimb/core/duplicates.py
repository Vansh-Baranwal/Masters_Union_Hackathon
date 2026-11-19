"""
3-layer duplicate detection (spec §11):

  Layer 1 — Semantic:   normalised ticket_id / UTR / order_id / QR payload
  Layer 2 — Exact file: SHA-256 match
  Layer 3 — Perceptual: pHash / aHash within Hamming threshold

Same ID from same sender   → RESEND   (not fraud signal, just dedup)
Same ID from diff sender   → REUSE    (needs review)
Perceptual match only      → SIMILAR  (signal, not conclusion; human decides)

Returns a DuplicateResult with all candidate matches — never a forced link.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import DBEvidence, DBInterpretation
from intake.fingerprint import compute_hamming_distance

import structlog
import json

log = structlog.get_logger(__name__)

PHASH_THRESHOLD = int(os.getenv("PHASH_SIMILARITY_THRESHOLD", "8"))
AHASH_THRESHOLD = int(os.getenv("AHASH_SIMILARITY_THRESHOLD", "6"))


class DuplicateKind(str, Enum):
    RESEND = "resend"           # exact SHA-256, same sender
    EXACT_REUSE = "exact_reuse" # exact SHA-256, different sender
    SEMANTIC = "semantic"       # shared identifier (UTR / ticket_id / order_id / QR)
    PERCEPTUAL = "perceptual"   # pHash / aHash within threshold
    NONE = "none"


@dataclass
class DuplicateCandidate:
    evidence_id: str
    sender_id: str
    kind: DuplicateKind
    matched_on: list[str]           # e.g. ["utr", "phash"]
    hamming_phash: Optional[int] = None
    hamming_ahash: Optional[int] = None
    score: float = 0.0              # 0.0–1.0 signal strength


@dataclass
class DuplicateResult:
    incoming_evidence_id: str
    candidates: list[DuplicateCandidate] = field(default_factory=list)

    @property
    def has_duplicates(self) -> bool:
        return bool(self.candidates)

    @property
    def strongest(self) -> Optional[DuplicateCandidate]:
        return max(self.candidates, key=lambda c: c.score) if self.candidates else None

    def to_dict(self) -> dict:
        return {
            "incoming_evidence_id": self.incoming_evidence_id,
            "has_duplicates": self.has_duplicates,
            "candidates": [
                {
                    "evidence_id": c.evidence_id,
                    "sender_id": c.sender_id,
                    "kind": c.kind.value,
                    "matched_on": c.matched_on,
                    "hamming_phash": c.hamming_phash,
                    "hamming_ahash": c.hamming_ahash,
                    "score": c.score,
                }
                for c in self.candidates
            ],
        }


# ─── Helpers ──────────────────────────────────────────────────────────────── #

def _get_semantic_keys(interp: DBInterpretation) -> dict[str, str | None]:
    """Pull the linkable identifiers out of a stored interpretation."""
    if not interp.fields_json:
        return {}
    try:
        f = json.loads(interp.fields_json)
    except Exception:
        return {}
    keys = {}
    for attr in ("utr", "order_id", "ticket_id", "qr_payload"):
        v = f.get(attr)
        if v and str(v).strip():
            keys[attr] = str(v).strip()
    return keys


def _semantic_overlap(
    keys_a: dict[str, str | None], keys_b: dict[str, str | None]
) -> list[str]:
    matched = []
    for attr, val in keys_a.items():
        if val and keys_b.get(attr) == val:
            matched.append(attr)
    return matched


def _phash_distance(phash_a: str, phash_b: str) -> int:
    """Hamming distance between two hex pHash strings."""
    try:
        return compute_hamming_distance(phash_a, phash_b)
    except Exception:
        return 999


# ─── Main detector ────────────────────────────────────────────────────────── #

async def detect_duplicates(
    session: AsyncSession,
    incoming: DBEvidence,
    incoming_interp: Optional[DBInterpretation],
    trip_id: Optional[str] = None,
) -> DuplicateResult:
    """
    Check `incoming` against all stored evidence (optionally scoped to a trip).
    Returns a DuplicateResult with zero or more candidates.
    """
    result = DuplicateResult(incoming_evidence_id=incoming.evidence_id)

    # ── Fetch candidate pool ─────────────────────────────────────────────── #
    q = select(DBEvidence).where(DBEvidence.evidence_id != incoming.evidence_id)
    if trip_id:
        q = q.where(DBEvidence.trip_id == trip_id)
    rows = list((await session.execute(q)).scalars().all())

    if not rows:
        return result

    # Pre-compute semantic keys for incoming
    incoming_keys = _get_semantic_keys(incoming_interp) if incoming_interp else {}

    for ev in rows:
        matched_on: list[str] = []
        kind = DuplicateKind.NONE
        h_phash: Optional[int] = None
        h_ahash: Optional[int] = None
        score = 0.0

        # ── Layer 2: Exact SHA-256 ────────────────────────────────────────── #
        if ev.sha256 == incoming.sha256:
            matched_on.append("sha256")
            kind = DuplicateKind.RESEND if ev.sender_id == incoming.sender_id else DuplicateKind.EXACT_REUSE
            score = 1.0

        # ── Layer 1: Semantic keys ────────────────────────────────────────── #
        if incoming_keys:
            ev_interp_q = await session.execute(
                select(DBInterpretation)
                .where(DBInterpretation.evidence_id == ev.evidence_id)
                .order_by(DBInterpretation.created_at.desc())
                .limit(1)
            )
            ev_interp = ev_interp_q.scalar_one_or_none()
            if ev_interp:
                ev_keys = _get_semantic_keys(ev_interp)
                overlap = _semantic_overlap(incoming_keys, ev_keys)
                if overlap:
                    matched_on.extend(overlap)
                    # Semantic is stronger than perceptual; upgrade kind if needed
                    if kind == DuplicateKind.NONE:
                        kind = DuplicateKind.SEMANTIC
                    sem_score = min(0.95, 0.70 + 0.10 * len(overlap))
                    score = max(score, sem_score)

        # ── Layer 3: Perceptual ───────────────────────────────────────────── #
        if ev.phash and incoming.phash:
            h_phash = _phash_distance(ev.phash, incoming.phash)
            if h_phash <= PHASH_THRESHOLD:
                matched_on.append(f"phash(d={h_phash})")
                if kind == DuplicateKind.NONE:
                    kind = DuplicateKind.PERCEPTUAL
                p_score = max(0.0, 1.0 - h_phash / (PHASH_THRESHOLD * 2))
                score = max(score, p_score)

        if ev.ahash and incoming.ahash:
            h_ahash = _phash_distance(ev.ahash, incoming.ahash)
            if h_ahash <= AHASH_THRESHOLD:
                if f"ahash" not in matched_on:
                    matched_on.append(f"ahash(d={h_ahash})")
                if kind == DuplicateKind.NONE:
                    kind = DuplicateKind.PERCEPTUAL
                a_score = max(0.0, 1.0 - h_ahash / (AHASH_THRESHOLD * 2))
                score = max(score, a_score)

        if kind != DuplicateKind.NONE:
            result.candidates.append(
                DuplicateCandidate(
                    evidence_id=ev.evidence_id,
                    sender_id=ev.sender_id,
                    kind=kind,
                    matched_on=matched_on,
                    hamming_phash=h_phash,
                    hamming_ahash=h_ahash,
                    score=round(score, 3),
                )
            )
            log.info(
                "duplicate_candidate",
                incoming=incoming.evidence_id,
                candidate=ev.evidence_id,
                kind=kind.value,
                score=round(score, 3),
                matched_on=matched_on,
            )

    return result
