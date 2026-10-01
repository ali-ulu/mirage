"""
MIRAGE API — Zehirli RAG / veri kaynağı guard ucu.

`POST /rag/inspect` — getirilen dokümanları bağlama almadan önce canary +
injection taramasından geçirir; `allow` / `quarantine` / `reject` kararı döner.
Eşikler `MIRAGE_RAG_*` env'inden okunur. `reject` edilen dokümanın metni
yanıtta boşaltılır (çağıran yanlışlıkla bağlama almasın).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..deps import require_api_token
from ...rag_guard import RAGGuard, SourceDoc, rag_policy_from_env, summarize

router = APIRouter(prefix="/rag", tags=["rag"])


class SourceDocModel(BaseModel):
    source_id: str = Field(..., description="Document identifier")
    text: str = Field(..., description="Retrieved document text")
    origin: str = Field("", description="Where it came from (e.g. 'web', 'confluence')")
    trust: str = Field("untrusted", pattern="^(trusted|untrusted)$")


class RAGInspectRequest(BaseModel):
    docs: list[SourceDocModel] = Field(..., min_length=1, description="Documents to screen")


def _guard() -> RAGGuard:
    return RAGGuard(**rag_policy_from_env())


@router.post("/inspect")
def inspect_documents(req: RAGInspectRequest, request: Request) -> dict:
    """
    Dokümanları tarar. Yanıt: `{"verdicts": [...], "summary": {...}}`.
    Her karar `action` (allow/quarantine/reject) + `sanitized_text` içerir.
    """
    require_api_token(request)
    guard = _guard()
    try:
        verdicts = guard.inspect_many(SourceDoc(**d.model_dump()) for d in req.docs)
    except Exception as exc:  # fail-safe: tarama hatasında bağlama alma
        raise HTTPException(status_code=500, detail=f"RAG guard error: {exc}")
    return {
        "verdicts": [v.to_dict() for v in verdicts],
        "summary": summarize(verdicts),
    }
