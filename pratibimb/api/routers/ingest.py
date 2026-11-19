"""
Ingest endpoint — receives an image, runs the full pipeline, returns assessment.
Used by the bot layer (Telegram / WhatsApp) to process screenshots programmatically.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from api.dependencies import get_store
from core.store import Store
from core.duplicates import detect_duplicates
from core.linking import propose_links
from core.trust import assess_trust, open_case_if_needed
from extraction.pipeline import run_extraction_pipeline
from intake.processor import build_evidence_record

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("")
async def ingest_screenshot(
    file: Annotated[UploadFile, File(description="Screenshot image file")],
    sender_id: Annotated[str, Form()],
    channel: Annotated[str, Form()] = "api",
    trip_id: Annotated[Optional[str], Form()] = None,
    language_hint: Annotated[Optional[str], Form()] = None,
    store: Store = Depends(get_store),
):
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(400, "Empty file")

    # 1. Build & save evidence record
    ev_record, _ = build_evidence_record(image_bytes, sender_id, channel, trip_id)
    await store.add_evidence(ev_record)

    # 2. Run extraction pipeline
    interp_record = await run_extraction_pipeline(image_bytes, ev_record.evidence_id)
    db_interp = await store.add_interpretation(interp_record)

    # 3. Get the DBEvidence we just saved
    db_ev = await store.get_evidence(ev_record.evidence_id)

    # 4. Duplicate detection
    dup_result = await detect_duplicates(store._s, db_ev, db_interp, trip_id)

    # 5. Link proposals
    proposals = await propose_links(store._s, ev_record.evidence_id, db_interp, trip_id, dup_result)
    for p in proposals:
        to_id = p.to_id if p.to_id else ev_record.evidence_id
        await store.add_relationship(
            from_id=p.from_id,
            to_id=to_id,
            rel_type=p.rel_type,
            basis=p.basis,
            score=p.score,
            created_by="system",
            plain_reason=p.plain_reason,
        )

    # 6. Trust assessment
    relationships = await store.get_relationships_for(ev_record.evidence_id)
    decisions = await store.get_decisions_for(ev_record.evidence_id)
    assessment = await assess_trust(
        session=store._s,
        store=store,
        evidence_id=ev_record.evidence_id,
        interp=db_interp,
        relationships=relationships,
        decisions=decisions,
    )

    # 7. Open case if needed
    if trip_id:
        await open_case_if_needed(store, assessment, trip_id, sender_id)

    return {
        "evidence_id": ev_record.evidence_id,
        "screenshot_type": interp_record.screenshot_type.value,
        "type_confidence": interp_record.type_confidence,
        "verdict": assessment.verdict,
        "reason": assessment.reason,
        "machine_states": assessment.machine_states,
        "overall_level": assessment.overall_level.value,
        "needs_challenge": assessment.needs_challenge,
        "challenge_message": assessment.challenge_message,
        "duplicates": dup_result.to_dict() if dup_result.has_duplicates else None,
        "links_proposed": len(proposals),
    }
