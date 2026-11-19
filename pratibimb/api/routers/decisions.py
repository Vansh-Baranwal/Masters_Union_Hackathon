"""Coordinator decision endpoints."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_store
from api.schemas import DecisionCreate, DecisionResponse
from core.store import Store

router = APIRouter(prefix="/decisions", tags=["decisions"])


@router.post("", response_model=DecisionResponse, status_code=201)
async def post_decision(
    body: DecisionCreate,
    store: Annotated[Store, Depends(get_store)],
):
    # Validate subject exists
    ev = await store.get_evidence(body.subject_ref)
    if not ev:
        raise HTTPException(404, f"Evidence {body.subject_ref!r} not found")

    # Build snapshot hash of what the coordinator saw
    seen_hash = body.seen_snapshot_hash
    if not seen_hash:
        # Auto-compute from latest interpretation
        interp = await store.get_latest_interpretation(body.subject_ref)
        if interp:
            snap = json.dumps({"interp_id": interp.interp_id, "fields": interp.fields_json}, sort_keys=True)
            seen_hash = hashlib.sha256(snap.encode()).hexdigest()

    dec = await store.add_decision(
        subject_ref=body.subject_ref,
        action=body.action,
        decided_by=body.decided_by,
        reason=body.reason or "",
        seen_snapshot_hash=seen_hash,
    )

    # If manually linking, create a MANUAL relationship
    if body.action == "linked_manually" and body.link_to_evidence_id:
        await store.add_relationship(
            from_id=body.subject_ref,
            to_id=body.link_to_evidence_id,
            rel_type="MANUAL",
            basis=["coordinator_decision"],
            score=1.0,
            created_by=body.decided_by,
            plain_reason=f"Manually linked by {body.decided_by}: {body.reason}",
        )

    # Resolve open case if approved or rejected
    if body.action in ("approved", "rejected"):
        case = await store.get_case_by_evidence(body.subject_ref)
        if case:
            await store.update_case_status(
                case.case_id,
                status="resolved",
                reason=f"{body.action} by {body.decided_by}",
            )

    return DecisionResponse(
        dec_id=dec.dec_id,
        subject_ref=dec.subject_ref,
        action=dec.action,
        decided_by=dec.decided_by,
        reason=dec.reason,
        created_at=dec.created_at,
    )
