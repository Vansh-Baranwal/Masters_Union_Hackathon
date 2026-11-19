"""Tests for the append-only store and hash chain."""
import pytest
from intake.models import EvidenceRecord, InterpretationRecord, ExtractedFields, ScreenshotType


def _make_evidence(ev_id="ev-001", sender="user-1", trip="trip-001"):
    return EvidenceRecord(
        evidence_id=ev_id,
        trip_id=trip,
        sender_id=sender,
        channel="test",
        received_at="2024-03-15T09:28:00+00:00",
        file_ref=f"/tmp/{ev_id}.bin",
        sha256="a" * 64,
        phash="b" * 16,
        ahash="c" * 16,
        status="received",
    )


def _make_interp(ev_id="ev-001", stype=ScreenshotType.UPI_SUCCESS):
    return InterpretationRecord(
        interp_id=f"interp-{ev_id}",
        evidence_id=ev_id,
        producer="test",
        model_version="fixture",
        screenshot_type=stype,
        type_confidence=0.90,
        fields=ExtractedFields(amount=40.0, currency="INR", utr="401234567890"),
        field_confidence={"amount": 0.90, "utr": 0.85},
        created_at="2024-03-15T09:28:30+00:00",
    )


@pytest.mark.asyncio
async def test_add_and_get_evidence(store):
    rec = _make_evidence()
    db_ev = await store.add_evidence(rec)
    assert db_ev.evidence_id == "ev-001"
    assert db_ev.record_hash is not None

    fetched = await store.get_evidence("ev-001")
    assert fetched is not None
    assert fetched.sender_id == "user-1"


@pytest.mark.asyncio
async def test_add_interpretation(store):
    await store.add_evidence(_make_evidence())
    interp = _make_interp()
    db_interp = await store.add_interpretation(interp)
    assert db_interp.interp_id == "interp-ev-001"
    assert db_interp.screenshot_type == "UPI_SUCCESS"

    latest = await store.get_latest_interpretation("ev-001")
    assert latest is not None
    assert latest.interp_id == "interp-ev-001"


@pytest.mark.asyncio
async def test_hash_chain_intact(store):
    await store.add_evidence(_make_evidence("ev-a", "u1", "trip-1"))
    await store.add_evidence(_make_evidence("ev-b", "u2", "trip-1"))
    result = await store.verify_chain()
    assert result["ok"] is True
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_add_relationship(store):
    await store.add_evidence(_make_evidence("ev-a"))
    await store.add_evidence(_make_evidence("ev-b"))
    rel = await store.add_relationship(
        from_id="ev-a", to_id="ev-b",
        rel_type="EXACT", basis=["utr"], score=1.0,
        created_by="system", plain_reason="Shared UTR",
    )
    assert rel.type == "EXACT"
    assert rel.record_hash is not None

    rels = await store.get_relationships_for("ev-a")
    assert len(rels) == 1


@pytest.mark.asyncio
async def test_add_decision(store):
    await store.add_evidence(_make_evidence("ev-a"))
    dec = await store.add_decision(
        subject_ref="ev-a", action="approved",
        decided_by="coord-1", reason="Looks good",
    )
    assert dec.action == "approved"
    decs = await store.get_decisions_for("ev-a")
    assert len(decs) == 1


@pytest.mark.asyncio
async def test_trip_lifecycle(store):
    trip = await store.create_trip("Test Trip", "coord-1")
    assert trip.join_code is not None
    assert len(trip.join_code) == 8

    fetched = await store.get_trip(trip.trip_id)
    assert fetched.name == "Test Trip"

    t = await store.add_traveller(trip.trip_id, "user-1", "Alice")
    assert t.display_name == "Alice"

    # Idempotent second add
    t2 = await store.add_traveller(trip.trip_id, "user-1", "Alice")
    assert t2.traveller_id == t.traveller_id

    travellers = await store.list_travellers(trip.trip_id)
    assert len(travellers) == 1


@pytest.mark.asyncio
async def test_case_open_and_resolve(store):
    trip = await store.create_trip("T", "c")
    await store.add_evidence(_make_evidence("ev-case", trip_id=trip.trip_id))

    case = await store.open_case(trip.trip_id, "ev-case", "user-1", "No ticket seen")
    assert case.status == "open"

    open_cases = await store.get_open_cases(trip.trip_id)
    assert len(open_cases) == 1

    await store.update_case_status(case.case_id, "resolved", "approved by coord")
    open_cases_after = await store.get_open_cases(trip.trip_id)
    assert len(open_cases_after) == 0
