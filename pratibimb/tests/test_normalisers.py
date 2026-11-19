"""Tests for field normalisers."""
import pytest
from intake.normalisers import (
    normalize_amount,
    normalize_timestamp,
    normalize_utr,
    normalize_order_or_ticket_id,
    mask_payer_name,
)


# ── Amount ────────────────────────────────────────────────────────────────── #

@pytest.mark.parametrize("raw,expected_amount,expected_currency", [
    ("₹40.00", 40.0, "INR"),
    ("Rs.40", 40.0, "INR"),
    ("INR 1,234.50", 1234.5, "INR"),
    ("40", 40.0, None),
    ("$12.99", 12.99, "USD"),
    (None, None, None),
    ("", None, None),
    ("N/A", None, None),
])
def test_normalize_amount(raw, expected_amount, expected_currency):
    amount, currency = normalize_amount(raw)
    assert amount == expected_amount
    if expected_currency:
        assert currency == expected_currency


# ── Timestamp ─────────────────────────────────────────────────────────────── #

@pytest.mark.parametrize("raw,should_be_none", [
    ("2024-03-15T09:28:00", False),
    ("15 Mar 2024 09:28 AM", False),
    ("15/03/2024 09:28", False),
    (None, True),
    ("", True),
    ("not a date", True),
])
def test_normalize_timestamp(raw, should_be_none):
    result = normalize_timestamp(raw)
    if should_be_none:
        assert result is None
    else:
        assert result is not None
        assert len(result) >= 10  # at least YYYY-MM-DD


# ── UTR ───────────────────────────────────────────────────────────────────── #

@pytest.mark.parametrize("raw,expected", [
    ("401234567890", "401234567890"),
    ("UPI/401234567890/NM", "401234567890"),
    ("  401234567890  ", "401234567890"),
    (None, None),
    ("", None),
    ("abc", None),   # too short / non-numeric
])
def test_normalize_utr(raw, expected):
    result, _ = normalize_utr(raw)
    assert result == expected


# ── Order / ticket ID ─────────────────────────────────────────────────────── #

@pytest.mark.parametrize("raw,kind,expected", [
    ("NM-2024-00123", "ticket_id", "NM-2024-00123"),
    ("  ORD-2024-00123  ", "order_id", "ORD-2024-00123"),
    (None, "ticket_id", None),
    ("", "order_id", None),
])
def test_normalize_order_or_ticket_id(raw, kind, expected):
    result, _ = normalize_order_or_ticket_id(raw, kind)
    assert result == expected


# ── Mask payer name ───────────────────────────────────────────────────────── #

@pytest.mark.parametrize("raw,should_contain_star", [
    ("Meera Singh", True),
    ("Ra", True),
    (None, False),
    ("", False),
])
def test_mask_payer_name(raw, should_contain_star):
    result = mask_payer_name(raw)
    if should_contain_star:
        assert result is not None
        assert "*" in result
    else:
        assert result is None or result == ""
