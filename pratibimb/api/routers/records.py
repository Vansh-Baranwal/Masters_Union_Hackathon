"""Evidence trail endpoint — full history for one item."""
from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_store
from api.schemas import TrailResponse
from core.store import Store

router = APIRouter(prefix="/records", tags=["records"])


@router.get("/{evidence_id}/trail", response_model=TrailResponse)
async def get_trail(
    evidence_id: str,
    store: Annotated[Store, Depends(get_store)],
):
    ev = await store.get_evidence(evidence_id)
    if not ev:
        raise HTTPException(404, "Evidence not found")

    interpretations = await store.get_all_interpretations(evidence_id)
    relationships = await store.get_relationships_for(evidence_id)
    decisions = await store.get_decisions_for(evidence_id)

    def _ev_dict(e) -> dict:
        return {
            "evidence_id": e.evidence_id,
            "trip_id": e.trip_id,
            "sender_id": e.sender_id,
            "channel": e.channel,
            "received_at": e.received_at,
            "sha256": e.sha256,
            "phash": e.phash,
            "status": e.status,
            # file_ref and raw image deliberately excluded from API response
        }

    def _interp_dict(i) -> dict:
        fields = json.loads(i.fields_json) if i.fields_json else {}
        fc = json.loads(i.field_confidence) if i.field_confidence else {}
        # Mask sensitive fields in API layer
        fields.pop("payer_name_masked", None)
        return {
            "interp_id": i.interp_id,
            "evidence_id": i.evidence_id,
            "producer": i.producer,
            "model_version": i.model_version,
            "screenshot_type": i.screenshot_type,
            "type_confidence": i.type_confidence,
            "fields": fields,
            "field_confidence": fc,
            "language_detected": i.language_detected,
            "created_at": i.created_at,
            "supersedes": i.supersedes,
            "qr_payload_parseable": i.qr_payload_parseable,
        }

    def _rel_dict(r) -> dict:
        return {
            "rel_id": r.rel_id,
            "from_id": r.from_id,
            "to_id": r.to_id,
            "type": r.type,
            "basis": json.loads(r.basis_json) if r.basis_json else [],
            "score": r.score,
            "plain_reason": r.plain_reason,
            "created_by": r.created_by,
            "created_at": r.created_at,
        }

    def _dec_dict(d) -> dict:
        return {
            "dec_id": d.dec_id,
            "subject_ref": d.subject_ref,
            "action": d.action,
            "decided_by": d.decided_by,
            "reason": d.reason,
            "created_at": d.created_at,
        }

    return TrailResponse(
        evidence_id=evidence_id,
        evidence=_ev_dict(ev),
        interpretations=[_interp_dict(i) for i in interpretations],
        relationships=[_rel_dict(r) for r in relationships],
        decisions=[_dec_dict(d) for d in decisions],
    )
