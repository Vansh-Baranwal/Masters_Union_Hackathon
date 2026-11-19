"""Tests for the EXACT/INFERRED/MANUAL/UNMATCHED linking engine."""
import json
import pytest
from intake.models import EvidenceRecord, InterpretationRecord, ExtractedFields, ScreenshotType
from core.linking import propose_links


def _ev(ev_id, trip_id="trip-1", sender="u1", sha256=None):
    return EvidenceRecord(
        evidence_id=ev_id, trip_id=trip_id, sender_id=sender,
        channel="test", received_at="2024-03-15T09:00:00+00:00",
        file_ref=f"/tmp/{ev_id}.bin",
        sha256=sha256 or ("a" * 64),
        phash="0" * 16, ahash=None, status="received",
    )


def _interp(ev_id, stype, utr=None, amount=None, timestamp=None,
            origin=None, dest=None, ticket_id=None, order_id=None):
    from core.models import DBInterpretation
    fields = {
        "utr": utr, "amount": amount, "timestamp": timestamp,
        "origin_station": origin, "destination_station": dest,
        "ticket_id": ticket_id, "order_id": order_id,
    }
    db = DBInterpretation()
    db.interp_id = f"i-{ev_id}"
    db.evidence_id = ev_id
    db.producer = "test"
    db.model_version = "fixture"
    db.screenshot_type = stype.value
    db.type_confidence = 0.90
    db.fields_json = json.dumps(fields)
    db.field_confidence = json.dumps({k: 0.90 for k, v in fields.items() if v})
    db.created_at = "2024-03-15T09:00:30+00:00"
    return db


@pytest.mark.asyncio
async def test_exact_link_on_shared_utr(store):
    # Store first evidence + interpretation
    ev1 = _ev("ev-pay-1")
    await store.add_evidence(ev1)
    # Insert interpretation directly via session
    interp1 = _interp("ev-pay-1", ScreenshotType.UPI_SUCCESS, utr="401234567890", amount=40.0)
    store._s.add(interp1)
    await store._s.flush()

    # New evidence with same UTR
    ev2 = _ev("ev-sms-1", sha256="b" * 64)
    db_ev2 = await store.add_evidence(ev2)
    interp2 = _interp("ev-sms-1", ScreenshotType.BANK_SMS, utr="401234567890", amount=40.0)
    store._s.add(interp2)
    await store._s.flush()

    proposals = await propose_links(store._s, "ev-sms-1", interp2, "trip-1")
    assert any(p.rel_type == "EXACT" and "utr" in p.basis for p in proposals)


@pytest.mark.asyncio
async def test_no_link_unmatched(store):
    ev1 = _ev("ev-a")
    await store.add_evidence(ev1)
    interp1 = _interp("ev-a", ScreenshotType.UPI_SUCCESS, utr="111", amount=100.0,
                      timestamp="2024-03-15T08:00:00")
    store._s.add(interp1)
    await store._s.flush()

    ev2 = _ev("ev-b", sha256="c" * 64)
    db_ev2 = await store.add_evidence(ev2)
    interp2 = _interp("ev-b", ScreenshotType.BANK_SMS, utr="999", amount=200.0,
                      timestamp="2024-03-15T20:00:00")
    store._s.add(interp2)
    await store._s.flush()

    proposals = await propose_links(store._s, "ev-b", interp2, "trip-1")
    types = [p.rel_type for p in proposals]
    assert "EXACT" not in types
    # Should produce UNMATCHED or INFERRED (not EXACT)
    assert all(t in ("UNMATCHED", "INFERRED") for t in types)


@pytest.mark.asyncio
async def test_no_proposals_when_no_candidates(store):
    ev = _ev("ev-solo")
    db_ev = await store.add_evidence(ev)
    interp = _interp("ev-solo", ScreenshotType.TICKET_QR, ticket_id="TK-001")
    store._s.add(interp)
    await store._s.flush()

    proposals = await propose_links(store._s, "ev-solo", interp, "trip-1")
    # No other evidence in trip → empty proposals
    assert proposals == []
