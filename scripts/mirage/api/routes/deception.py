"""
MIRAGE API — Otonom deception orkestrasyon ucu.

`POST /deception/playbook` — bir saldırgan mesaj dizisini yeni bir honeypot
oturumunda sürer; sızıntı yakalanınca decoy döndürülür (rotate). `GET
/deception/summary` süreç-içi oturum/çıktı özetini verir. Orkestratör honeypot
motorunu paylaşır (tek kaynak: `api.deps`).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..deps import get_deception_orchestrator, require_api_token

router = APIRouter(prefix="/deception", tags=["deception"])


class PlaybookRequest(BaseModel):
    messages: list[str] = Field(..., min_length=1, description="Attacker message sequence")
    token: Optional[str] = Field(None, description="Honeytoken UUID to embed in the decoy")
    context: Optional[str] = Field(None, description="Decoy context (e.g. 'finance-share')")


@router.post("/playbook")
async def run_playbook(req: PlaybookRequest, request: Request) -> dict:
    """
    Playbook'u sürer ve `DeceptionOutcome` döner: `{session_id, turns, leaked,
    canary_hits, stopped_reason, rotated_to}`. Fail-safe: akış hataları yutulur.
    """
    require_api_token(request)
    orchestrator = get_deception_orchestrator()
    try:
        outcome = await orchestrator.run_playbook(
            req.messages, token=req.token, context=req.context
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Deception error: {exc}")
    return outcome.to_dict()


@router.get("/summary")
def deception_summary(request: Request) -> dict:
    """Aktif oturumlar + yakalama çıktılarının özeti (in-memory)."""
    require_api_token(request)
    return get_deception_orchestrator().summary()
