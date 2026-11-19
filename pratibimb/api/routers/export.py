"""Claims export endpoint — CSV / XLSX / JSON."""
from __future__ import annotations

import io
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.dependencies import get_store
from api.schemas import ClaimRow, ClaimsExportResponse
from core.store import Store
from core.trust import assess_trust
from core.models import DBInterpretation, DBRelationship, DBDecision

router = APIRouter(prefix="/export", tags=["export"])


async def _build_rows(trip_id: str, store: Store) -> list[ClaimRow]:
    trip = await store.get_trip(trip_id)
    if not trip:
        raise HTTPException(404, "Trip not found")

    travellers = await store.list_travellers(trip_id)
    sender_to_name = {t.sender_id: t.display_name for t in travellers}

    evidence_list = await store.find_evidence_by_trip(trip_id)
    rows: list[ClaimRow] = []

    for ev in evidence_list:
        interp = await store.get_latest_interpretation(ev.evidence_id)
        if not interp:
            continue

        fields = json.loads(interp.fields_json) if interp.fields_json else {}
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

        rel_type = None
        rel_basis = ""
        if relationships:
            strongest = max(relationships, key=lambda r: r.score)
            rel_type = strongest.type
            rel_basis = ", ".join(json.loads(strongest.basis_json) if strongest.basis_json else [])

        coord_decision = None
        coord_reason = None
        for d in sorted(decisions, key=lambda x: x.created_at, reverse=True):
            if d.action in ("approved", "rejected"):
                coord_decision = d.action
                coord_reason = d.reason
                break

        rows.append(ClaimRow(
            evidence_id=ev.evidence_id,
            sender_id=ev.sender_id,
            display_name=sender_to_name.get(ev.sender_id),
            received_at=ev.received_at,
            screenshot_type=interp.screenshot_type,
            amount=fields.get("amount"),
            currency=fields.get("currency"),
            timestamp=fields.get("timestamp"),
            utr=fields.get("utr"),
            ticket_id=fields.get("ticket_id"),
            order_id=fields.get("order_id"),
            origin_station=fields.get("origin_station"),
            destination_station=fields.get("destination_station"),
            fare=fields.get("fare"),
            verdict=assessment.verdict,
            overall_level=assessment.overall_level.value,
            relationship_type=rel_type,
            relationship_basis=rel_basis,
            coordinator_decision=coord_decision,
            coordinator_reason=coord_reason,
        ))

    return rows


@router.get("/claims")
async def export_claims(
    trip_id: str = Query(...),
    fmt: str = Query("json", pattern="^(json|csv|xlsx)$"),
    store: Store = Depends(get_store),
):
    rows = await _build_rows(trip_id, store)

    if fmt == "json":
        return ClaimsExportResponse(trip_id=trip_id, rows=rows, total=len(rows))

    # Build a flat list of dicts for CSV / XLSX
    flat = [r.model_dump() for r in rows]

    if fmt == "csv":
        import csv
        buf = io.StringIO()
        if flat:
            writer = csv.DictWriter(buf, fieldnames=list(flat[0].keys()))
            writer.writeheader()
            writer.writerows(flat)
        buf.seek(0)
        return StreamingResponse(
            io.BytesIO(buf.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=claims_{trip_id}.csv"},
        )

    if fmt == "xlsx":
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Claims"
        if flat:
            ws.append(list(flat[0].keys()))
            for row in flat:
                ws.append(list(row.values()))
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=claims_{trip_id}.xlsx"},
        )
