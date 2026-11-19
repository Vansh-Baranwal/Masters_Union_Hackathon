"""Tests for the evaluation scorer logic."""
import pytest
from eval.scorer import (
    classification_accuracy,
    field_extraction_accuracy,
    linking_accuracy,
    false_accept_rate,
)


GT_CLASS = [
    {"evidence_id": "ev-1", "screenshot_type": "UPI_SUCCESS", "split": "test"},
    {"evidence_id": "ev-2", "screenshot_type": "TICKET_QR",   "split": "test"},
    {"evidence_id": "ev-3", "screenshot_type": "BANK_SMS",    "split": "test"},
]

PRED_CLASS_PERFECT = [
    {"evidence_id": "ev-1", "screenshot_type": "UPI_SUCCESS", "type_confidence": 0.94, "split": "test"},
    {"evidence_id": "ev-2", "screenshot_type": "TICKET_QR",   "type_confidence": 0.92, "split": "test"},
    {"evidence_id": "ev-3", "screenshot_type": "BANK_SMS",    "type_confidence": 0.90, "split": "test"},
]

PRED_CLASS_ONE_WRONG = [
    {"evidence_id": "ev-1", "screenshot_type": "UPI_SUCCESS",        "type_confidence": 0.94, "split": "test"},
    {"evidence_id": "ev-2", "screenshot_type": "UPI_FAILED_PENDING",  "type_confidence": 0.60, "split": "test"},
    {"evidence_id": "ev-3", "screenshot_type": "BANK_SMS",            "type_confidence": 0.90, "split": "test"},
]


def test_classification_perfect():
    result = classification_accuracy(GT_CLASS, PRED_CLASS_PERFECT)
    assert result["overall_accuracy"] == 1.0
    assert result["correct"] == 3


def test_classification_one_wrong():
    result = classification_accuracy(GT_CLASS, PRED_CLASS_ONE_WRONG)
    assert result["overall_accuracy"] == pytest.approx(2 / 3, abs=0.01)
    assert result["correct"] == 2


def test_field_extraction_all_correct():
    gt = [{"evidence_id": "ev-1", "screenshot_type": "UPI_SUCCESS",
           "fields": {"amount": 40.0, "utr": "401234567890"}}]
    pred = [{"evidence_id": "ev-1",
             "fields": {"amount": 40.0, "utr": "401234567890"}}]
    result = field_extraction_accuracy(gt, pred)
    assert result["amount"]["correct"] == 1
    assert result["amount"]["miss"] == 0
    assert result["utr"]["correct"] == 1


def test_field_extraction_one_miss():
    gt = [{"evidence_id": "ev-1", "fields": {"amount": 40.0, "utr": "401234567890"}}]
    pred = [{"evidence_id": "ev-1", "fields": {"amount": 40.0, "utr": None}}]
    result = field_extraction_accuracy(gt, pred)
    assert result["utr"]["miss"] == 1


def test_linking_accuracy_perfect():
    gt = [{"from_id": "ev-1", "to_id": "ev-2", "relationship_type": "EXACT"}]
    pred = [{"from_id": "ev-1", "to_id": "ev-2", "relationship_type": "EXACT", "score": 1.0}]
    result = linking_accuracy(gt, pred)
    assert result["overall_accuracy"] == 1.0


def test_false_accept_rate_no_bad():
    gt = [
        {"evidence_id": "ev-1", "is_bad": False},
        {"evidence_id": "ev-2", "is_bad": False},
    ]
    pred = [
        {"evidence_id": "ev-1", "verdict": "corroborated"},
        {"evidence_id": "ev-2", "verdict": "corroborated"},
    ]
    result = false_accept_rate(gt, pred)
    assert result["false_accepts"] == 0
    assert result["coverage"] == 1.0


def test_false_accept_rate_catches_bad():
    gt = [
        {"evidence_id": "ev-1", "is_bad": True},
        {"evidence_id": "ev-2", "is_bad": False},
    ]
    pred = [
        {"evidence_id": "ev-1", "verdict": "corroborated"},   # wrongly cleared
        {"evidence_id": "ev-2", "verdict": "corroborated"},
    ]
    result = false_accept_rate(gt, pred)
    assert result["false_accepts"] == 1
    assert result["false_accept_rate"] == 1.0
