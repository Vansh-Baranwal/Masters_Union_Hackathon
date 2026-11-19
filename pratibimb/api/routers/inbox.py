"""Coordinator inbox — exceptions only, with reasons and relationship types."""
from __future__ import annotations

import json
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_store
from api.schemas import InboxItem, InboxResponse
from core.store import Store
from core.trust import assess_trust
from sqlalchemy import select
from core.models import DBInterpretation, DBRelationship, DBDecision, DBCase

router = APIRouter(prefix="/trips", tags=["inbox"])

EXCEPTION_VERDICTS = {"needs_review", "unreadable"}


@router.get("/{trip_id}/inbox", response_model=InboxResponse)
async def get_inbox(
    trip_id: str,
    store: Annotated[Store, Depends(get_store)],
):
    trip = await store.get_trip(trip_id)
    if not trip:
        raise HTTPException(404, "Trip not found")

    evidence_list = await store.find_evidence_by_trip(trip_id)
    exceptions: list[InboxItem] = []

    for ev in evidence_list:
        interp = await store.get_latest_interpretation(ev.evidence_id)
        if not interp:
            continue

        relationships = await store.get_relationships_for(ev.evidence_id)
        decisions = await store.get_decisions_for(ev.evidence_id)

        assessment = await assess_trust(
            session=store._s,
            store=store,
            evidence_id=ev.evidence_id,
            interp=interp,
            relationships=relationships,
            decisions=decisions,
        )

        if assessment.verdict not in EXCEPTION_VERDICTS:
            continue

        # Pick strongest relationship for display
        rel_type: Optional[str] = None
        rel_basis: list[str] = []
        if relationships:
            strongest = max(relationships, key=lambda r: r.score)
            rel_type = strongest.type
            rel_basis = json.loads(strongest.basis_json) if strongest.basis_json else []

        # Case id if open
        case = await store.get_case_by_evidence(ev.evidence_id)

        exceptions.append(InboxItem(
            evidence_id=ev.evidence_id,
            sender_id=ev.sender_id,
            received_at=ev.received_at,
            screenshot_type=interp.screenshot_type,
            type_confidence=interp.type_confidence,
            verdict=assessment.verdict,
            reason=assessment.reason,
            machine_states=assessment.machine_states,
            overall_level=assessment.overall_level.value,
            relationship_type=rel_type,
            relationship_basis=rel_basis,
            case_id=case.case_id if case else None,
            needs_challenge=assessment.needs_challenge,
        ))

    return InboxResponse(
        trip_id=trip_id,
        total_items=len(evidence_list),
        exceptions=exceptions,
    )
