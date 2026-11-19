"""Tests for trust assessment and adaptive challenge."""
import json
import pytest
from intake.models import ScreenshotType
from core.models import DBInterpretation, DBRelationship, DBDecision
from core.trust import assess_trust, EvidenceLevel


def _mock_interp(stype: str, confidence: float = 0.90, utr=None, amount=None) -> DBInterpretation:
    fields = {"amount": amount, "utr": utr, "timestamp": "2024-03-15T09:28:00"}
    fc = {"amount": 0.90 if amount else 0.0, "utr": 0.85 if utr else 0.0, "timestamp": 0.80}
    interp = DBInterpretation()
    interp.interp_id = "test-interp"
    interp.evidence_id = "test-ev"
    interp.producer = "test"
    interp.model_version = "fixture"
    interp.screenshot_type = stype
    interp.type_confidence = confidence
    interp.fields_json = json.dumps(fields)
    interp.field_confidence = json.dumps(fc)
    interp.created_at = "2024-03-15T09:28:30+00:00"
    return interp


def _mock_rel(rel_type: str) -> DBRelationship:
    rel = DBRelationship()
    rel.rel_id = "test-rel"
    rel.from_id = "test-ev"
    rel.to_id = "other-ev"
    rel.type = rel_type
    rel.basis_json = json.dumps(["utr"])
    rel.score = 1.0 if rel_type == "EXACT" else 0.65
    rel.plain_reason = "test"
    rel.created_by = "system"
    rel.created_at = "2024-03-15T09:30:00+00:00"
    return rel


@pytest.mark.asyncio
async def test_upi_success_with_exact_link(store):
    interp = _mock_interp("UPI_SUCCESS", utr="401234567890", amount=40.0)
    rel = _mock_rel("EXACT")
    assessment = await assess_trust(
        session=store._s, store=store,
        evidence_id="test-ev", interp=interp,
        relationships=[rel], decisions=[],
    )
    assert assessment.verdict == "corroborated"
    assert "payment_seen" in assessment.machine_states
    assert "linked_exact" in assessment.machine_states
    assert assessment.needs_challenge is False


@pytest.mark.asyncio
async def test_upi_success_no_link_no_utr(store):
    interp = _mock_interp("UPI_SUCCESS", utr=None, amount=40.0)
    assessment = await assess_trust(
        session=store._s, store=store,
        evidence_id="test-ev", interp=interp,
        relationships=[], decisions=[],
    )
    assert assessment.verdict == "needs_review"
    assert assessment.needs_challenge is True
    assert assessment.challenge_message is not None


@pytest.mark.asyncio
async def test_ticket_qr_no_link(store):
    interp = _mock_interp("TICKET_QR", confidence=0.92)
    assessment = await assess_trust(
        session=store._s, store=store,
        evidence_id="test-ev", interp=interp,
        relationships=[], decisions=[],
    )
    # Ticket seen but no payment linked — extracted, not needs_review
    assert assessment.verdict == "extracted"
    assert "ticket_seen" in assessment.machine_states


@pytest.mark.asyncio
async def test_suspect_notice_always_needs_review(store):
    interp = _mock_interp("SUSPECT_NOTICE", confidence=0.93)
    assessment = await assess_trust(
        session=store._s, store=store,
        evidence_id="test-ev", interp=interp,
        relationships=[], decisions=[],
    )
    assert assessment.verdict == "needs_review"
    assert "suspect_pattern" in (assessment.challenge_message or "").lower() or assessment.needs_challenge


@pytest.mark.asyncio
async def test_low_confidence_other_is_unreadable(store):
    interp = _mock_interp("OTHER", confidence=0.20)
    assessment = await assess_trust(
        session=store._s, store=store,
        evidence_id="test-ev", interp=interp,
        relationships=[], decisions=[],
    )
    assert assessment.verdict == "unreadable"


@pytest.mark.asyncio
async def test_verdict_never_uses_fraud_or_verified(store):
    for stype in ("UPI_SUCCESS", "TICKET_QR", "SUSPECT_NOTICE", "OTHER", "BANK_SMS"):
        interp = _mock_interp(stype, utr="12345", amount=40.0)
        assessment = await assess_trust(
            session=store._s, store=store,
            evidence_id="test-ev", interp=interp,
            relationships=[], decisions=[],
        )
        combined = (assessment.verdict + " " + assessment.reason).lower()
        assert "fraud" not in combined, f"'fraud' found in assessment for {stype}"
        assert "verified" not in combined, f"'verified' found in assessment for {stype}"
