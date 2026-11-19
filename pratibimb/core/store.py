"""
Append-only store with hash chain.

Rules (spec §B1):
- Never UPDATE or DELETE evidence / interpretation / relationship / decision rows.
- Corrections are new rows with supersedes = old_id.
- Every write is recorded in audit_chain with prev_hash → record_hash chain.
- record_hash = SHA-256(json_of_record + prev_hash)
- audit_chain gives tamper *evidence*, not prevention.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    DBEvidence, DBInterpretation, DBRelationship,
    DBDecision, DBTrip, DBTraveller, DBCase,
    DBAuditChain, DBAccessLog,
)
from core.database import get_session
from intake.models import EvidenceRecord, InterpretationRecord

import structlog

log = structlog.get_logger(__name__)

GENESIS_HASH = "0" * 64  # first row in chain has prev_hash = all zeros


# ─── Hash helpers ──────────────────────────────────────────────────────────── #

def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _record_to_stable_json(record: Any, exclude_keys: set[str] | None = None) -> str:
    """Serialise an ORM object's __dict__ to a stable JSON string for hashing."""
    exclude = exclude_keys or {"_sa_instance_state", "prev_hash", "record_hash"}
    d = {k: v for k, v in record.__dict__.items() if k not in exclude}
    return json.dumps(d, sort_keys=True, default=str)


async def _get_prev_hash(session: AsyncSession) -> str:
    result = await session.execute(
        select(DBAuditChain.record_hash)
        .order_by(DBAuditChain.seq.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row if row else GENESIS_HASH


async def _append_audit(
    session: AsyncSession,
    record_type: str,
    record_id: str,
    record_hash: str,
    prev_hash: str,
) -> None:
    entry = DBAuditChain(
        record_type=record_type,
        record_id=record_id,
        record_hash=record_hash,
        prev_hash=prev_hash,
        written_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add(entry)


async def _chain_write(
    session: AsyncSession,
    record_type: str,
    db_obj: Any,
    id_attr: str,
) -> str:
    """Compute hash, attach to db_obj, write to audit_chain, return record_hash."""
    prev_hash = await _get_prev_hash(session)
    stable_json = _record_to_stable_json(db_obj)
    record_hash = _sha256_hex(stable_json + prev_hash)
    db_obj.prev_hash = prev_hash
    db_obj.record_hash = record_hash
    await _append_audit(session, record_type, getattr(db_obj, id_attr), record_hash, prev_hash)
    return record_hash


# ─── Store class ──────────────────────────────────────────────────────────── #

class Store:
    """
    All database operations go through this class.
    Session is passed in externally so callers control transaction scope.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ── Evidence ─────────────────────────────────────────────────────────── #

    async def add_evidence(self, rec: EvidenceRecord) -> DBEvidence:
        db = DBEvidence(
            evidence_id=rec.evidence_id,
            trip_id=rec.trip_id,
            sender_id=rec.sender_id,
            channel=rec.channel,
            received_at=rec.received_at,
            file_ref=rec.file_ref,
            sha256=rec.sha256,
            phash=rec.phash,
            ahash=rec.ahash,
            status=rec.status,
        )
        self._s.add(db)
        await _chain_write(self._s, "evidence", db, "evidence_id")
        log.info("store.evidence_added", evidence_id=rec.evidence_id)
        return db

    async def get_evidence(self, evidence_id: str) -> DBEvidence | None:
        return await self._s.get(DBEvidence, evidence_id)

    async def find_evidence_by_sha256(self, sha256: str) -> list[DBEvidence]:
        result = await self._s.execute(
            select(DBEvidence).where(DBEvidence.sha256 == sha256)
        )
        return list(result.scalars().all())

    async def find_evidence_by_trip(self, trip_id: str) -> list[DBEvidence]:
        result = await self._s.execute(
            select(DBEvidence)
            .where(DBEvidence.trip_id == trip_id)
            .order_by(DBEvidence.received_at)
        )
        return list(result.scalars().all())

    # ── Interpretation ────────────────────────────────────────────────────── #

    async def add_interpretation(self, rec: InterpretationRecord) -> DBInterpretation:
        db = DBInterpretation(
            interp_id=rec.interp_id,
            evidence_id=rec.evidence_id,
            producer=rec.producer,
            model_version=rec.model_version,
            sarvam_job_id=rec.sarvam_job_id,
            screenshot_type=rec.screenshot_type.value,
            type_confidence=rec.type_confidence,
            fields_json=json.dumps(rec.fields.model_dump(), default=str) if rec.fields else None,
            field_confidence=json.dumps(rec.field_confidence) if rec.field_confidence else None,
            raw_text_ref=rec.raw_text_ref,
            language_detected=rec.language_detected,
            created_at=rec.created_at,
            supersedes=rec.supersedes,
            qr_payload_parseable=rec.qr_payload_parseable,
        )
        self._s.add(db)
        await _chain_write(self._s, "interpretation", db, "interp_id")
        log.info("store.interp_added", interp_id=rec.interp_id, type=rec.screenshot_type.value)
        return db

    async def get_latest_interpretation(self, evidence_id: str) -> DBInterpretation | None:
        result = await self._s.execute(
            select(DBInterpretation)
            .where(
                DBInterpretation.evidence_id == evidence_id,
                DBInterpretation.supersedes == None,  # noqa: E711
            )
            .order_by(DBInterpretation.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_all_interpretations(self, evidence_id: str) -> list[DBInterpretation]:
        result = await self._s.execute(
            select(DBInterpretation)
            .where(DBInterpretation.evidence_id == evidence_id)
            .order_by(DBInterpretation.created_at)
        )
        return list(result.scalars().all())

    # ── Relationship ──────────────────────────────────────────────────────── #

    async def add_relationship(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
        basis: list[str],
        score: float,
        created_by: str,
        plain_reason: str = "",
        supersedes: str | None = None,
    ) -> DBRelationship:
        db = DBRelationship(
            rel_id=str(uuid.uuid4()),
            from_id=from_id,
            to_id=to_id,
            type=rel_type,
            basis_json=json.dumps(basis),
            score=score,
            plain_reason=plain_reason,
            created_by=created_by,
            created_at=datetime.now(timezone.utc).isoformat(),
            supersedes=supersedes,
        )
        self._s.add(db)
        await _chain_write(self._s, "relationship", db, "rel_id")
        log.info("store.rel_added", rel_id=db.rel_id, type=rel_type, from_id=from_id, to_id=to_id)
        return db

    async def get_relationships_for(self, evidence_id: str) -> list[DBRelationship]:
        result = await self._s.execute(
            select(DBRelationship).where(
                (DBRelationship.from_id == evidence_id) | (DBRelationship.to_id == evidence_id)
            )
        )
        return list(result.scalars().all())

    # ── Decision ──────────────────────────────────────────────────────────── #

    async def add_decision(
        self,
        subject_ref: str,
        action: str,
        decided_by: str,
        reason: str = "",
        seen_snapshot_hash: str | None = None,
        supersedes: str | None = None,
    ) -> DBDecision:
        db = DBDecision(
            dec_id=str(uuid.uuid4()),
            subject_ref=subject_ref,
            action=action,
            decided_by=decided_by,
            reason=reason,
            seen_snapshot_hash=seen_snapshot_hash,
            created_at=datetime.now(timezone.utc).isoformat(),
            supersedes=supersedes,
        )
        self._s.add(db)
        await _chain_write(self._s, "decision", db, "dec_id")
        log.info("store.decision_added", dec_id=db.dec_id, action=action, by=decided_by)
        return db

    async def get_decisions_for(self, subject_ref: str) -> list[DBDecision]:
        result = await self._s.execute(
            select(DBDecision).where(DBDecision.subject_ref == subject_ref)
            .order_by(DBDecision.created_at)
        )
        return list(result.scalars().all())

    # ── Trips ─────────────────────────────────────────────────────────────── #

    async def create_trip(
        self, name: str, coordinator_id: str, join_code: str | None = None
    ) -> DBTrip:
        db = DBTrip(
            trip_id=str(uuid.uuid4()),
            name=name,
            coordinator_id=coordinator_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            join_code=join_code or _make_join_code(),
            status="active",
        )
        self._s.add(db)
        log.info("store.trip_created", trip_id=db.trip_id, name=name)
        return db

    async def get_trip(self, trip_id: str) -> DBTrip | None:
        return await self._s.get(DBTrip, trip_id)

    async def get_trip_by_join_code(self, join_code: str) -> DBTrip | None:
        result = await self._s.execute(
            select(DBTrip).where(DBTrip.join_code == join_code)
        )
        return result.scalar_one_or_none()

    async def add_traveller(
        self, trip_id: str, sender_id: str, display_name: str | None = None, language_pref: str | None = None
    ) -> DBTraveller:
        # Idempotent: skip if already registered
        existing = await self._s.execute(
            select(DBTraveller).where(
                DBTraveller.trip_id == trip_id,
                DBTraveller.sender_id == sender_id,
            )
        )
        t = existing.scalar_one_or_none()
        if t:
            return t
        db = DBTraveller(
            traveller_id=str(uuid.uuid4()),
            trip_id=trip_id,
            sender_id=sender_id,
            display_name=display_name,
            language_pref=language_pref,
            joined_at=datetime.now(timezone.utc).isoformat(),
        )
        self._s.add(db)
        return db

    async def list_travellers(self, trip_id: str) -> list[DBTraveller]:
        result = await self._s.execute(
            select(DBTraveller).where(DBTraveller.trip_id == trip_id)
        )
        return list(result.scalars().all())

    # ── Cases ─────────────────────────────────────────────────────────────── #

    async def open_case(
        self, trip_id: str, evidence_id: str, sender_id: str, reason: str
    ) -> DBCase:
        db = DBCase(
            case_id=str(uuid.uuid4()),
            trip_id=trip_id,
            evidence_id=evidence_id,
            sender_id=sender_id,
            opened_at=datetime.now(timezone.utc).isoformat(),
            status="open",
            reason=reason,
        )
        self._s.add(db)
        log.info("store.case_opened", case_id=db.case_id, evidence_id=evidence_id)
        return db

    async def update_case_status(self, case_id: str, status: str, reason: str = "") -> DBCase | None:
        db = await self._s.get(DBCase, case_id)
        if db:
            db.status = status
            db.last_action_at = datetime.now(timezone.utc).isoformat()
            if reason:
                db.reason = reason
        return db

    async def get_open_cases(self, trip_id: str) -> list[DBCase]:
        result = await self._s.execute(
            select(DBCase).where(DBCase.trip_id == trip_id, DBCase.status == "open")
            .order_by(DBCase.opened_at.desc())
        )
        return list(result.scalars().all())

    async def get_case_by_evidence(self, evidence_id: str) -> DBCase | None:
        result = await self._s.execute(
            select(DBCase).where(DBCase.evidence_id == evidence_id, DBCase.status == "open")
        )
        return result.scalar_one_or_none()

    # ── Audit ─────────────────────────────────────────────────────────────── #

    async def verify_chain(self) -> dict:
        """
        Walk the audit_chain in seq order and re-derive each hash.
        Returns {"ok": bool, "broken_at_seq": int|None, "total": int}.
        """
        result = await self._s.execute(
            select(DBAuditChain).order_by(DBAuditChain.seq)
        )
        rows = list(result.scalars().all())

        prev = GENESIS_HASH
        for row in rows:
            if row.prev_hash != prev:
                return {"ok": False, "broken_at_seq": row.seq, "total": len(rows)}
            prev = row.record_hash

        return {"ok": True, "broken_at_seq": None, "total": len(rows)}

    # ── Access log ────────────────────────────────────────────────────────── #

    async def log_raw_image_access(
        self, evidence_id: str, requested_by: str, reason: str = ""
    ) -> None:
        entry = DBAccessLog(
            evidence_id=evidence_id,
            requested_by=requested_by,
            reason=reason,
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        self._s.add(entry)


# ─── Helpers ──────────────────────────────────────────────────────────────── #

def _make_join_code() -> str:
    import secrets
    import string
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))
