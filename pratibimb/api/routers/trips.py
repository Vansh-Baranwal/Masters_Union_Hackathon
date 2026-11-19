"""Trip management endpoints."""
from __future__ import annotations

import secrets
import string
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_store
from api.schemas import TripCreate, TripJoinCodeResponse, TripSummary, TravellersRow
from core.store import Store
from sqlalchemy import select, func
from core.models import DBEvidence, DBCase

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("", response_model=TripSummary, status_code=201)
async def create_trip(
    body: TripCreate,
    store: Annotated[Store, Depends(get_store)],
):
    trip = await store.create_trip(name=body.name, coordinator_id=body.coordinator_id)
    return TripSummary(
        trip_id=trip.trip_id,
        name=trip.name,
        coordinator_id=trip.coordinator_id,
        status=trip.status,
        created_at=trip.created_at,
        join_code=trip.join_code,
        traveller_count=0,
        evidence_count=0,
        open_case_count=0,
        travellers=[],
    )


@router.post("/{trip_id}/join-code", response_model=TripJoinCodeResponse)
async def refresh_join_code(
    trip_id: str,
    store: Annotated[Store, Depends(get_store)],
):
    trip = await store.get_trip(trip_id)
    if not trip:
        raise HTTPException(404, "Trip not found")
    alphabet = string.ascii_uppercase + string.digits
    trip.join_code = "".join(secrets.choice(alphabet) for _ in range(8))
    return TripJoinCodeResponse(trip_id=trip_id, join_code=trip.join_code)


@router.get("/{trip_id}/summary", response_model=TripSummary)
async def get_trip_summary(
    trip_id: str,
    store: Annotated[Store, Depends(get_store)],
):
    trip = await store.get_trip(trip_id)
    if not trip:
        raise HTTPException(404, "Trip not found")

    travellers = await store.list_travellers(trip_id)
    evidence_list = await store.find_evidence_by_trip(trip_id)
    open_cases = await store.get_open_cases(trip_id)

    return TripSummary(
        trip_id=trip.trip_id,
        name=trip.name,
        coordinator_id=trip.coordinator_id,
        status=trip.status,
        created_at=trip.created_at,
        join_code=trip.join_code,
        traveller_count=len(travellers),
        evidence_count=len(evidence_list),
        open_case_count=len(open_cases),
        travellers=[
            TravellersRow(
                traveller_id=t.traveller_id,
                sender_id=t.sender_id,
                display_name=t.display_name,
                language_pref=t.language_pref,
                joined_at=t.joined_at,
            )
            for t in travellers
        ],
    )
