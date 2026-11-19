"""
SQLAlchemy ORM models for Pratibimb's append-only store.

Design rules (from spec §B1):
- No UPDATE or DELETE on evidence, interpretations, relationships, decisions.
- Corrections → new row with supersedes = old_id.
- Every row gets prev_hash and record_hash for the hash chain.
- Trips, travellers, cases, audit_chain, access_log are operational tables
  (cases can be updated as they progress).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer,
    String, Text, JSON, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────── #
#  Immutable record tables                                                    #
# ─────────────────────────────────────────────────────────────────────────── #

class DBEvidence(Base):
    __tablename__ = "evidence"

    evidence_id:    Mapped[str]           = mapped_column(String, primary_key=True)
    trip_id:        Mapped[Optional[str]] = mapped_column(String, ForeignKey("trips.trip_id"), nullable=True, index=True)
    sender_id:      Mapped[str]           = mapped_column(String, nullable=False, index=True)
    channel:        Mapped[str]           = mapped_column(String, nullable=False)
    received_at:    Mapped[str]           = mapped_column(String, nullable=False)  # ISO
    file_ref:       Mapped[str]           = mapped_column(String, nullable=False)
    sha256:         Mapped[str]           = mapped_column(String(64), nullable=False, index=True)
    phash:          Mapped[str]           = mapped_column(String(64), nullable=False)
    ahash:          Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status:         Mapped[str]           = mapped_column(String, default="received")
    # Hash chain
    prev_hash:      Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    record_hash:    Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    interpretations: Mapped[list["DBInterpretation"]] = relationship(back_populates="evidence")


class DBInterpretation(Base):
    __tablename__ = "interpretations"

    interp_id:          Mapped[str]           = mapped_column(String, primary_key=True)
    evidence_id:        Mapped[str]           = mapped_column(String, ForeignKey("evidence.evidence_id"), nullable=False, index=True)
    producer:           Mapped[str]           = mapped_column(String, nullable=False)
    model_version:      Mapped[str]           = mapped_column(String, nullable=False)
    sarvam_job_id:      Mapped[Optional[str]] = mapped_column(String, nullable=True)
    screenshot_type:    Mapped[str]           = mapped_column(String, nullable=False, index=True)
    type_confidence:    Mapped[float]         = mapped_column(Float, nullable=False)
    fields_json:        Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON blob
    field_confidence:   Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON blob
    field_sources:      Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON blob
    raw_text_ref:       Mapped[Optional[str]] = mapped_column(String, nullable=True)
    language_detected:  Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at:         Mapped[str]           = mapped_column(String, nullable=False)
    supersedes:         Mapped[Optional[str]] = mapped_column(String, ForeignKey("interpretations.interp_id"), nullable=True)
    qr_payload_parseable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    normalized_corrections: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    # Hash chain
    prev_hash:          Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    record_hash:        Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    evidence: Mapped["DBEvidence"] = relationship(back_populates="interpretations")


class DBRelationship(Base):
    __tablename__ = "relationships"

    rel_id:      Mapped[str]           = mapped_column(String, primary_key=True)
    from_id:     Mapped[str]           = mapped_column(String, ForeignKey("evidence.evidence_id"), nullable=False, index=True)
    to_id:       Mapped[str]           = mapped_column(String, ForeignKey("evidence.evidence_id"), nullable=False, index=True)
    type:        Mapped[str]           = mapped_column(String, nullable=False)   # EXACT|INFERRED|MANUAL|UNMATCHED
    basis_json:  Mapped[Optional[str]] = mapped_column(Text, nullable=True)      # JSON list of matched attributes
    score:       Mapped[float]         = mapped_column(Float, default=0.0)
    plain_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by:  Mapped[str]           = mapped_column(String, nullable=False)   # 'system' or user_id
    created_at:  Mapped[str]           = mapped_column(String, nullable=False)
    supersedes:  Mapped[Optional[str]] = mapped_column(String, ForeignKey("relationships.rel_id"), nullable=True)
    # Hash chain
    prev_hash:   Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    record_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class DBDecision(Base):
    __tablename__ = "decisions"

    dec_id:             Mapped[str]           = mapped_column(String, primary_key=True)
    subject_ref:        Mapped[str]           = mapped_column(String, nullable=False, index=True)
    action:             Mapped[str]           = mapped_column(String, nullable=False)  # approved|rejected|proof_requested|linked_manually
    decided_by:         Mapped[str]           = mapped_column(String, nullable=False)
    reason:             Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    seen_snapshot_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at:         Mapped[str]           = mapped_column(String, nullable=False)
    supersedes:         Mapped[Optional[str]] = mapped_column(String, ForeignKey("decisions.dec_id"), nullable=True)
    # Hash chain
    prev_hash:          Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    record_hash:        Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


# ─────────────────────────────────────────────────────────────────────────── #
#  Operational tables                                                         #
# ─────────────────────────────────────────────────────────────────────────── #

class DBTrip(Base):
    __tablename__ = "trips"

    trip_id:      Mapped[str]           = mapped_column(String, primary_key=True)
    name:         Mapped[str]           = mapped_column(String, nullable=False)
    coordinator_id: Mapped[str]         = mapped_column(String, nullable=False)
    created_at:   Mapped[str]           = mapped_column(String, nullable=False)
    join_code:    Mapped[Optional[str]] = mapped_column(String(16), nullable=True, unique=True, index=True)
    status:       Mapped[str]           = mapped_column(String, default="active")  # active|closed

    travellers:   Mapped[list["DBTraveller"]] = relationship(back_populates="trip")
    cases:        Mapped[list["DBCase"]]      = relationship(back_populates="trip")


class DBTraveller(Base):
    __tablename__ = "travellers"

    traveller_id: Mapped[str]           = mapped_column(String, primary_key=True)
    trip_id:      Mapped[str]           = mapped_column(String, ForeignKey("trips.trip_id"), nullable=False, index=True)
    sender_id:    Mapped[str]           = mapped_column(String, nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    language_pref: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    joined_at:    Mapped[str]           = mapped_column(String, nullable=False)

    trip: Mapped["DBTrip"] = relationship(back_populates="travellers")


class DBCase(Base):
    __tablename__ = "cases"

    case_id:          Mapped[str]           = mapped_column(String, primary_key=True)
    trip_id:          Mapped[str]           = mapped_column(String, ForeignKey("trips.trip_id"), nullable=False, index=True)
    evidence_id:      Mapped[str]           = mapped_column(String, ForeignKey("evidence.evidence_id"), nullable=False, index=True)
    sender_id:        Mapped[str]           = mapped_column(String, nullable=False)
    opened_at:        Mapped[str]           = mapped_column(String, nullable=False)
    last_action_at:   Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status:           Mapped[str]           = mapped_column(String, default="open")  # open|resolved|stale
    reason:           Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stale_flag:       Mapped[bool]          = mapped_column(Boolean, default=False)

    trip: Mapped["DBTrip"] = relationship(back_populates="cases")


class DBAuditChain(Base):
    """One row per record write, ordered by sequence. Verifier walks this table."""
    __tablename__ = "audit_chain"

    seq:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_type: Mapped[str]           = mapped_column(String, nullable=False)   # evidence|interpretation|relationship|decision
    record_id:   Mapped[str]           = mapped_column(String, nullable=False, index=True)
    record_hash: Mapped[str]           = mapped_column(String(64), nullable=False)
    prev_hash:   Mapped[str]           = mapped_column(String(64), nullable=False)
    written_at:  Mapped[str]           = mapped_column(String, nullable=False)


class DBAccessLog(Base):
    """Logs every explicit request to access raw image data."""
    __tablename__ = "access_log"

    log_id:      Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    evidence_id: Mapped[str]           = mapped_column(String, ForeignKey("evidence.evidence_id"), nullable=False)
    requested_by: Mapped[str]          = mapped_column(String, nullable=False)
    reason:      Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_at: Mapped[str]          = mapped_column(String, nullable=False)
