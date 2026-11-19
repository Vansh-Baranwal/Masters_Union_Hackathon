"""
Full extraction pipeline called per incoming image.
Orchestrates: Sarvam Extract → Digitise → Classify → Field Build → Return.

The caller (intake/processor.py or the API layer) holds the EvidenceRecord
already saved in the store. This module returns a completed InterpretationRecord.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import structlog

from intake.models import ExtractedFields, InterpretationRecord, ScreenshotType
from intake.processor import build_stub_interpretation
from extraction.sarvam_client import SarvamClient, SarvamError
from extraction.classifier import classify_screenshot, CONFIDENCE_THRESHOLD
from extraction.field_builder import build_fields_from_sarvam
from intake.qr_decoder import QRDecoder

log = structlog.get_logger(__name__)

SCHEMAS_DIR = Path(__file__).parent / "schemas"
_qr = QRDecoder()

# LLM classification threshold: below this we try Sarvam-105B
LLM_ESCALATION_THRESHOLD = CONFIDENCE_THRESHOLD


def _load_schema(screenshot_type: ScreenshotType) -> dict:
    schema_file = SCHEMAS_DIR / f"{screenshot_type.value}.json"
    if schema_file.exists():
        return json.loads(schema_file.read_text(encoding="utf-8"))
    return {}


async def run_extraction_pipeline(
    image_bytes: bytes,
    evidence_id: str,
    raw_text_storage_dir: Optional[Path] = None,
    language_hint: Optional[str] = None,
) -> InterpretationRecord:
    """
    Full extraction pipeline for one image.
    Returns a completed InterpretationRecord (not yet persisted — caller saves it).
    Falls back gracefully at every step; never raises to the caller on API errors.
    """
    raw_text = ""
    sarvam_fields: dict = {}
    sarvam_job_id: Optional[str] = None
    model_version = "sarvam-vision-1.5"
    qr_payload: Optional[str] = None
    qr_parsed: Optional[dict] = None
    qr_parseable: Optional[bool] = None

    # ── Step 1: Local QR decode ──────────────────────────────────────────── #
    try:
        qr_payload, qr_parsed, qr_parseable = _qr.decode(image_bytes)
        if qr_payload:
            log.info("qr_decoded", evidence_id=evidence_id, parseable=qr_parseable)
    except Exception as exc:
        log.warning("qr_decode_error", evidence_id=evidence_id, error=str(exc))

    # ── Step 2: Sarvam Digitise (raw OCR text, also the fallback) ────────── #
    async with SarvamClient() as client:
        try:
            digitise_result = await client.digitise(image_bytes)
            raw_text = digitise_result.get("text", "")
            if raw_text_storage_dir:
                raw_path = raw_text_storage_dir / f"{evidence_id}_raw.txt"
                raw_path.write_text(raw_text, encoding="utf-8")
            log.info("digitise_done", evidence_id=evidence_id, chars=len(raw_text))
        except SarvamError as exc:
            log.warning("digitise_failed", evidence_id=evidence_id, error=str(exc))

        # ── Step 3: Rule-based classification ───────────────────────────── #
        screenshot_type, type_confidence, type_reason = classify_screenshot(
            raw_text, qr_found=bool(qr_payload)
        )

        # ── Step 4: LLM classification escalation ───────────────────────── #
        if type_confidence < LLM_ESCALATION_THRESHOLD and raw_text.strip():
            try:
                llm_result = await client.classify_with_llm(raw_text)
                llm_type_str = llm_result.get("screenshot_type", "OTHER")
                llm_conf = float(llm_result.get("confidence", 0.0))
                # Only upgrade if LLM is more confident
                if llm_conf > type_confidence:
                    screenshot_type = ScreenshotType(llm_type_str)
                    type_confidence = llm_conf
                    type_reason = f"llm: {llm_result.get('reason', '')}"
                    model_version = "sarvam-vision-1.5+105b"
                    log.info("llm_classification_used", evidence_id=evidence_id, type=llm_type_str, conf=llm_conf)
            except Exception as exc:
                log.warning("llm_classify_failed", evidence_id=evidence_id, error=str(exc))

        # ── Step 5: Sarvam Extract with per-type schema ──────────────────── #
        schema = _load_schema(screenshot_type)
        if schema:
            try:
                extract_result = await client.extract(
                    image_bytes, schema, screenshot_type.value, language_hint
                )
                sarvam_job_id = extract_result.get("job_id")
                sarvam_fields = extract_result.get("fields", {})
                log.info("extract_done", evidence_id=evidence_id, type=screenshot_type.value, job_id=sarvam_job_id)
            except SarvamError as exc:
                log.warning("extract_failed_using_digitise", evidence_id=evidence_id, error=str(exc))
                # Fallback: parse raw text as a flat dict of key patterns
                sarvam_fields = {}

    # ── Step 6: Inject QR payload into sarvam_fields if not already present #
    if qr_payload and not sarvam_fields.get("qr_payload"):
        sarvam_fields["qr_payload"] = qr_payload

    # ── Step 7: Build typed ExtractedFields ─────────────────────────────── #
    fields, field_confidence, field_sources, corrections = build_fields_from_sarvam(
        sarvam_fields,
        raw_text=raw_text,
        qr_parsed=qr_parsed,
        base_confidence=type_confidence,
    )

    # ── Step 8: Determine language ──────────────────────────────────────── #
    language_detected = fields.language_detected or language_hint

    # ── Step 9: Save raw text ref ──────────────────────────────────────── #
    raw_text_ref = None
    if raw_text_storage_dir:
        rp = raw_text_storage_dir / f"{evidence_id}_raw.txt"
        raw_text_ref = str(rp)

    return build_stub_interpretation(
        evidence_id=evidence_id,
        screenshot_type=screenshot_type,
        type_confidence=type_confidence,
        fields=fields,
        field_confidence=field_confidence,
        field_sources=field_sources,
        raw_text_ref=raw_text_ref,
        language_detected=language_detected,
        sarvam_job_id=sarvam_job_id,
        model_version=model_version,
        qr_payload_parseable=qr_parseable,
    )
