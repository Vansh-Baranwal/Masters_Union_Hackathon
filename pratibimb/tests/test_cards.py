"""Tests for the reply-card generator."""
import pytest
from cards.generator import generate_reply_card, CardVerdict


@pytest.mark.parametrize("verdict,stype", [
    ("corroborated",  "UPI_SUCCESS"),
    ("extracted",     "TICKET_QR"),
    ("needs_review",  "BOT_ERROR"),
    ("unreadable",    "OTHER"),
    ("needs_review",  "SUSPECT_NOTICE"),
])
def test_card_generates_png(verdict, stype):
    png = generate_reply_card(
        assessment_verdict=verdict,
        screenshot_type=stype,
        reason="Test reason for this card.",
        lang="en",
        amount=40.0,
        currency="INR",
        origin_station="Indiranagar",
        destination_station="MG Road",
        evidence_id_short="abcd1234",
    )
    assert isinstance(png, bytes)
    assert len(png) > 500               # non-trivial PNG
    assert png[:4] == b"\x89PNG"        # valid PNG magic bytes


def test_card_with_hindi():
    png = generate_reply_card(
        assessment_verdict="corroborated",
        screenshot_type="UPI_SUCCESS",
        reason="Payment and ticket linked.",
        lang="hi-IN",
        amount=40.0,
    )
    assert png[:4] == b"\x89PNG"


def test_card_with_kannada():
    png = generate_reply_card(
        assessment_verdict="needs_review",
        screenshot_type="UPI_FAILED_PENDING",
        reason="No ticket found for this payment.",
        lang="kn-IN",
    )
    assert png[:4] == b"\x89PNG"


def test_card_all_nulls():
    """Card must not crash when all optional fields are None."""
    png = generate_reply_card(
        assessment_verdict="unreadable",
        screenshot_type="OTHER",
        reason="Could not classify.",
    )
    assert png[:4] == b"\x89PNG"
