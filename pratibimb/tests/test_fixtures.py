"""Tests for fixture loader and fixture data integrity."""
import pytest
from fixtures.loader import load_fixture, load_all_fixtures, fixture_names
from intake.models import ScreenshotType


def test_fixture_names_non_empty():
    names = fixture_names()
    assert len(names) >= 8, "Expected at least 8 fixture files"


def test_load_ticket_qr_fixture():
    rec = load_fixture("ticket_qr_01")
    assert rec.screenshot_type == ScreenshotType.TICKET_QR
    assert rec.fields.ticket_id == "NM-2024-00123"
    assert rec.fields.origin_station == "Indiranagar"
    assert rec.fields.destination_station == "MG Road"
    assert rec.fields.fare == 40.0
    assert rec.qr_payload_parseable is True


def test_load_upi_success_fixture():
    rec = load_fixture("upi_success_01")
    assert rec.screenshot_type == ScreenshotType.UPI_SUCCESS
    assert rec.fields.utr == "401234567890"
    assert rec.fields.amount == 40.0


def test_load_suspect_notice_fixture():
    rec = load_fixture("suspect_notice_01")
    assert rec.screenshot_type == ScreenshotType.SUSPECT_NOTICE
    assert rec.type_confidence >= 0.90


def test_load_all_fixtures_no_crash():
    all_recs = load_all_fixtures()
    assert len(all_recs) >= 8
    for r in all_recs:
        assert isinstance(r.screenshot_type, ScreenshotType)
        assert 0.0 <= r.type_confidence <= 1.0


def test_duplicate_fixture_has_same_ticket_id():
    orig = load_fixture("ticket_qr_01")
    dup = load_fixture("ticket_qr_duplicate_01")
    assert orig.fields.ticket_id == dup.fields.ticket_id
    assert orig.evidence_id != dup.evidence_id


def test_other_fixture_has_zero_confidence_fields():
    rec = load_fixture("other_01")
    assert rec.screenshot_type == ScreenshotType.OTHER
    assert rec.type_confidence < 0.5
    assert rec.fields.ticket_id is None
    assert rec.fields.utr is None
