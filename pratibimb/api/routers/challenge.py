"""Adaptive evidence challenge endpoint."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_store
from api.schemas import ChallengeResponse
from core.store import Store
from core.trust import assess_trust

router = APIRouter(prefix="/challenge", tags=["challenge"])


@router.post("/{evidence_id}", response_model=ChallengeResponse)
async def trigger_challenge(
    evidence_id: str,
    store: Annotated[Store, Depends(get_store)],
):
    ev = await store.get_evidence(evidence_id)
    if not ev:
        raise HTTPException(404, "Evidence not found")

    interp = await store.get_latest_interpretation(evidence_id)
    if not interp:
        raise HTTPException(422, "No interpretation available yet")

    relationships = await store.get_relationships_for(evidence_id)
    decisions = await store.get_decisions_for(evidence_id)

    assessment = await assess_trust(
        session=store._s,
        store=store,
        evidence_id=evidence_id,
        interp=interp,
        relationships=relationships,
        decisions=decisions,
    )

    if not assessment.needs_challenge:
        return ChallengeResponse(
            evidence_id=evidence_id,
            challenge_sent=False,
            message="No challenge needed for this item.",
        )

    # In production the bot sends this directly to the user via channel.
    # Here we return the message for the API caller (bot layer picks it up).
    return ChallengeResponse(
        evidence_id=evidence_id,
        challenge_sent=True,
        message=assessment.challenge_message or "",
    )
