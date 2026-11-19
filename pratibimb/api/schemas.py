"""Pydantic request/response schemas for the Pratibimb API."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Trips ───────────────────────────────────────────────────────────────── #

class TripCreate(BaseModel):
    name: str
    coordinator_id: str


class TripJoinCodeResponse(BaseModel):
    trip_id: str
    join_code: str


class TravellersRow(BaseModel):
    traveller_id: str
    sender_id: str
    display_name: Optional[str]
    language_pref: Optional[str]
    joined_at: str


class TripSummary(BaseModel):
    trip_id: str
    name: str
    coordinator_id: str
    status: str
    created_at: str
    join_code: Optional[str]
    traveller_count: int
    evidence_count: int
    open_case_count: int
    travellers: list[TravellersRow]


# ── Inbox ────────────────────────────────────────────────────────────────── #

class InboxItem(BaseModel):
    evidence_id: str
    sender_id: str
    received_at: str
    screenshot_type: str
    type_confidence: float
    verdict: str
    reason: str
    machine_states: list[str]
    overall_level: str
    relationship_type: Optional[str]
    relationship_basis: list[str]
    case_id: Optional[str]
    needs_challenge: bool


class InboxResponse(BaseModel):
    trip_id: str
    total_items: int
    exceptions: list[InboxItem]


# ── Trail ────────────────────────────────────────────────────────────────── #

class TrailResponse(BaseModel):
    evidence_id: str
    evidence: dict
    interpretations: list[dict]
    relationships: list[dict]
    decisions: list[dict]


# ── Decisions ────────────────────────────────────────────────────────────── #

class DecisionCreate(BaseModel):
    subject_ref: str
    action: str = Field(..., pattern="^(approved|rejected|proof_requested|linked_manually)$")
    decided_by: str
    reason: Optional[str] = ""
    seen_snapshot_hash: Optional[str] = None
    link_to_evidence_id: Optional[str] = None   # used when action=linked_manually


class DecisionResponse(BaseModel):
    dec_id: str
    subject_ref: str
    action: str
    decided_by: str
    reason: Optional[str]
    created_at: str


# ── Challenge ────────────────────────────────────────────────────────────── #

class ChallengeResponse(BaseModel):
    evidence_id: str
    challenge_sent: bool
    message: str


# ── Audit ────────────────────────────────────────────────────────────────── #

class AuditVerifyResponse(BaseModel):
    ok: bool
    broken_at_seq: Optional[int]
    total: int


# ── Export ───────────────────────────────────────────────────────────────── #

class ClaimRow(BaseModel):
    evidence_id: str
    sender_id: str
    display_name: Optional[str]
    received_at: str
    screenshot_type: str
    amount: Optional[float]
    currency: Optional[str]
    timestamp: Optional[str]
    utr: Optional[str]
    ticket_id: Optional[str]
    order_id: Optional[str]
    origin_station: Optional[str]
    destination_station: Optional[str]
    fare: Optional[float]
    verdict: str
    overall_level: str
    relationship_type: Optional[str]
    relationship_basis: str
    coordinator_decision: Optional[str]
    coordinator_reason: Optional[str]


class ClaimsExportResponse(BaseModel):
    trip_id: str
    rows: list[ClaimRow]
    total: int
