"""
MIRAGE API — Ajan davranış analitiği ucu.

`POST /behavior/analyze` — triyaj kayıtlarından (veya düz sözlüklerden)
saldırgan niyeti profilini üretir. Girdi ya `events` ile verilir ya da
`token` verilerek triyaj defterinden çekilir (Supabase gerekir).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..deps import get_triage_store, require_api_token
from ...behavior import analyze
from ...supabase_registry import SupabaseNotConfiguredError

router = APIRouter(prefix="/behavior", tags=["behavior"])


class BehaviorAnalyzeRequest(BaseModel):
    events: Optional[list[dict[str, Any]]] = Field(
        None, description="Explicit triage-like records (dicts)"
    )
    token: Optional[str] = Field(
        None, description="Honeytoken UUID; events omitted → loaded from the triage ledger"
    )
    distinct_actors: Optional[int] = Field(None, description="Distinct actor/IP count, if known")


def _load_events(req: BehaviorAnalyzeRequest) -> list[Any]:
    if req.events is not None:
        return req.events
    if req.token:
        try:
            store = get_triage_store()
        except SupabaseNotConfiguredError:
            raise HTTPException(
                status_code=503,
                detail="Triage ledger not configured (SUPABASE_URL/KEY); pass `events` instead",
            )
        return store.list_for_token(req.token)
    raise HTTPException(status_code=422, detail="Provide either `events` or `token`")


@router.post("/analyze")
def analyze_behavior(req: BehaviorAnalyzeRequest, request: Request) -> dict:
    """
    Saldırgan niyeti profilini döner: `{intent_score, intent_level,
    sophistication, signals, event_count, recommended_action}`.
    """
    require_api_token(request)
    events = _load_events(req)
    try:
        profile = analyze(events, distinct_actors=req.distinct_actors)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Behavior analysis error: {exc}")
    return profile.to_dict()
