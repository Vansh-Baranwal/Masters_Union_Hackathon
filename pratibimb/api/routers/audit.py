"""Audit hash-chain verification endpoint."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from api.dependencies import get_store
from api.schemas import AuditVerifyResponse
from core.store import Store

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/verify", response_model=AuditVerifyResponse)
async def verify_chain(store: Annotated[Store, Depends(get_store)]):
    result = await store.verify_chain()
    return AuditVerifyResponse(
        ok=result["ok"],
        broken_at_seq=result.get("broken_at_seq"),
        total=result["total"],
    )
