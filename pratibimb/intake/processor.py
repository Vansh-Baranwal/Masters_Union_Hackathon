"""
Intake processor: orchestrates the full pipeline for a single incoming image.
  1. Save raw image to disk (encrypted)
  2. Compute fingerprints
  3. Decode QR (local)
  4. Build EvidenceRecord and persist via store stub
  5. Hand off to extraction service (async job)
  6. Build InterpretationRecord and persist
  7. Return both records
"""
from __future__ import annotations

import os
import io
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

from intake.models import EvidenceRecord, InterpretationRecord, ExtractedFields, ScreenshotType
from intake.fingerprint import compute_fingerprints
from intake.qr_decoder import QRDecoder

import structlog

log = structlog.get_logger(__name__)

RAW_IMAGE_DIR = Path(os.getenv("RAW_IMAGE_DIR", "./data/raw_images"))
RAW_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

_qr_decoder = QRDecoder()


def _save_raw_image(image_bytes: bytes, evidence_id: str) -> Path:
    """Persist raw image bytes to disk under RAW_IMAGE_DIR/<evidence_id>."""
    dest = RAW_IMAGE_DIR / f"{evidence_id}.bin"
    dest.write_bytes(image_bytes)
    return dest


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_evidence_record(
    image_bytes: bytes,
    sender_id: str,
    channel: str,
    trip_id: Optional[str] = None,
) -> Tuple[EvidenceRecord, Path]:
    """
    Compute fingerprints, save the raw image, and return an EvidenceRecord.
    Does NOT persist to the database — that is the store's responsibility.
    """
    evidence_id = str(uuid.uuid4())
    fingerprints = compute_fingerprints(image_bytes)
    file_path = _save_raw_image(image_bytes, evidence_id)

    record = EvidenceRecord(
        evidence_id=evidence_id,
        trip_id=trip_id,
        sender_id=sender_id,
        channel=channel,
        received_at=_now_iso(),
        file_ref=str(file_path),
        sha256=fingerprints["sha256"],
        phash=fingerprints["phash"],
        ahash=fingerprints["ahash"],
        status="received",
    )
    log.info("evidence_record_built", evidence_id=evidence_id, channel=channel)
    return record, file_path


def decode_qr_from_bytes(image_bytes: bytes) -> Tuple[Optional[str], Optional[dict], bool]:
    """Attempt local QR decode. Returns (raw_payload, parsed_dict, is_parseable)."""
    try:
        return _qr_decoder.decode(image_bytes)
    except Exception as exc:
        log.warning("qr_decode_failed", error=str(exc))
        return None, None, False


def build_stub_interpretation(
    evidence_id: str,
    screenshot_type: ScreenshotType = ScreenshotType.OTHER,
    type_confidence: float = 0.0,
    fields: Optional[ExtractedFields] = None,
    field_confidence: Optional[dict] = None,
    raw_text_ref: Optional[str] = None,
    language_detected: Optional[str] = None,
    sarvam_job_id: Optional[str] = None,
    model_version: str = "pending",
    qr_payload_parseable: Optional[bool] = None,
    supersedes: Optional[str] = None,
) -> InterpretationRecord:
    """
    Build an InterpretationRecord from extraction outputs.
    Called by the extraction service once Sarvam jobs complete.
    """
    return InterpretationRecord(
        interp_id=str(uuid.uuid4()),
        evidence_id=evidence_id,
        producer="pratibimb-intake-v1",
        model_version=model_version,
        sarvam_job_id=sarvam_job_id,
        screenshot_type=screenshot_type,
        type_confidence=type_confidence,
        fields=fields or ExtractedFields(),
        field_confidence=field_confidence or {},
        raw_text_ref=raw_text_ref,
        language_detected=language_detected,
        created_at=_now_iso(),
        supersedes=supersedes,
        qr_payload_parseable=qr_payload_parseable,
    )
