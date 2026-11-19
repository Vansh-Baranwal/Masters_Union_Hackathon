"""Tests for the 3-layer duplicate detection engine."""
import json
import pytest
from intake.models import EvidenceRecord, InterpretationRecord, ExtractedFields, ScreenshotType
from core.duplicates import detect_duplicates, DuplicateKind


def _ev(ev_id, sender, sha256="x" * 64, phash="0" * 16):
    return EvidenceRecord(
        evidence_id=ev_id, trip_id="trip-1", sender_id=sender,
        channel="test", received_at="2024-03-15T09:00:00+00:00",
        file_ref=f"/tmp/{ev_id}.bin", sha256=sha256, phash=phash, ahash=None, status="received",
    )


def _interp(ev_id, utr=None, ticket_id=None, amount=None):
    return InterpretationRecord(
        interp_id=f"i-{ev_id}", evidence_id=ev_id,
        producer="test", model_version="fixture",
        screenshot_type=ScreenshotType.UPI_SUCCESS,
        type_confidence=0.90,
        fields=ExtractedFields(utr=utr, ticket_id=ticket_id, amount=amount),
        field_confidence={},
        created_at="2024-03-15T09:00:30+00:00",
    )


@pytest.mark.asyncio
async def test_no_duplicates_empty_store(store):
    ev = _ev("ev-new", "u1")
    db_ev = await store.add_evidence(ev)
    result = await detect_duplicates(store._s, db_ev, None, "trip-1")
    assert not result.has_duplicates


@pytest.mark.asyncio
async def test_exact_sha256_same_sender(store):
    sha = "a" * 64
    ev1 = _ev("ev-1", "u1", sha256=sha)
    ev2 = _ev("ev-2", "u1", sha256=sha)
    await store.add_evidence(ev1)
    db_ev2 = await store.add_evidence(ev2)
    result = await detect_duplicates(store._s, db_ev2, None, "trip-1")
    assert result.has_duplicates
    assert result.strongest.kind == DuplicateKind.RESEND


@pytest.mark.asyncio
async def test_exact_sha256_different_sender(store):
    sha = "b" * 64
    ev1 = _ev("ev-1", "u1", sha256=sha)
    ev2 = _ev("ev-2", "u2", sha256=sha)
    await store.add_evidence(ev1)
    db_ev2 = await store.add_evidence(ev2)
    result = await detect_duplicates(store._s, db_ev2, None, "trip-1")
    assert result.has_duplicates
    assert result.strongest.kind == DuplicateKind.EXACT_REUSE


@pytest.mark.asyncio
async def test_semantic_utr_match(store):
    ev1 = _ev("ev-1", "u1", sha256="a" * 64)
    ev2 = _ev("ev-2", "u2", sha256="b" * 64)
    interp1 = _interp("ev-1", utr="401234567890")
    interp2 = _interp("ev-2", utr="401234567890")
    await store.add_evidence(ev1)
    await store.add_interpretation(interp1)
    db_ev2 = await store.add_evidence(ev2)
    db_i2 = await store.add_interpretation(interp2)
    result = await detect_duplicates(store._s, db_ev2, db_i2, "trip-1")
    assert result.has_duplicates
    assert result.strongest.kind == DuplicateKind.SEMANTIC
    assert "utr" in result.strongest.matched_on
