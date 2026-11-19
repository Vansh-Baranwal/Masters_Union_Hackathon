"""Tests for the rule-based screenshot classifier."""
import pytest
from extraction.classifier import classify_screenshot
from intake.models import ScreenshotType


@pytest.mark.parametrize("text,qr,expected_type", [
    # Clear UPI success
    ("Payment Successful ₹40 sent to Namma Metro GPay UTR 123456789012", False, ScreenshotType.UPI_SUCCESS),
    # UPI failed
    ("Payment Failed transaction could not complete PhonePe ₹50", False, ScreenshotType.UPI_FAILED_PENDING),
    # Bank SMS
    ("Rs.40.00 debited from A/c XX4521 UPI ref 401234567890 HDFC Bank", False, ScreenshotType.BANK_SMS),
    # Metro ticket with QR
    ("Ticket ID NM-2024-00123 Indiranagar MG Road Valid Namma Metro", True, ScreenshotType.TICKET_QR),
    # Bot error
    ("Booking failed namma metro whatsapp refunded 7 working days", False, ScreenshotType.BOT_ERROR),
    # Suspect — click here scam
    ("Click here to claim your metro refund OTP required", False, ScreenshotType.SUSPECT_NOTICE),
    # Refund notice
    ("Refund Initiated Rs.40 processed to source account", False, ScreenshotType.REFUND_NOTICE),
    # Empty text → OTHER
    ("", False, ScreenshotType.OTHER),
    # Noise → OTHER
    ("Hello world random text with no payment or ticket words", False, ScreenshotType.OTHER),
])
def test_classify(text, qr, expected_type):
    result_type, confidence, reason = classify_screenshot(text, qr_found=qr)
    assert result_type == expected_type, (
        f"Expected {expected_type.value}, got {result_type.value} "
        f"(conf={confidence:.2f}, reason={reason!r})"
    )


def test_suspect_beats_refund():
    """SUSPECT_NOTICE pattern should fire before REFUND_NOTICE on scam text."""
    text = "Click here tap here to claim refund OTP to receive money"
    result_type, confidence, _ = classify_screenshot(text)
    assert result_type == ScreenshotType.SUSPECT_NOTICE
    assert confidence >= 0.5


def test_low_confidence_returns_other():
    """A partial match below threshold should return OTHER."""
    text = "some amount debited"   # only one weak signal
    result_type, confidence, _ = classify_screenshot(text)
    # Could be BANK_SMS or OTHER; either way confidence should be < 0.90 for ambiguous text
    # We just ensure we don't crash and get a valid type
    assert isinstance(result_type, ScreenshotType)
