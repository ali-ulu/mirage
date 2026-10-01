"""
MIRAGE API — Merkle + harici zaman damgası çapası ucu.

`POST /evidence/anchor` — bir token'ın kanıt zincirinden Merkle kökü kurup
çapalar (varsayılan `NullAnchor`; gerçek TSA/OTS için `anchor` enjekte edilir).
`POST /evidence/proof` — belirli bir kaydın Merkle dahil olma kanıtını üretir.
`POST /evidence/verify-proof` — kanıtı yalnızca kök + yolla doğrular (state yok).

Non-claim: `NullAnchor` kriptografik üçüncü-taraf iddiası taşımaz; yalnızca
yerel bütünlük kanıtıdır.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..deps import get_evidence_store, require_api_token
from ...merkle_anchor import (
    AnchorError,
    ProofStep,
    anchor_evidence_chain,
    merkle_proof,
    merkle_root,
    verify_proof,
)
from ...supabase_registry import SupabaseNotConfiguredError

router = APIRouter(prefix="/evidence", tags=["evidence"])


class AnchorRequest(BaseModel):
    token: str = Field(..., description="Honeytoken UUID whose evidence chain to anchor")


class ProofRequest(BaseModel):
    token: str = Field(..., description="Honeytoken UUID")
    index: int = Field(..., ge=0, description="Record index (canonical chain_seq order)")


class VerifyProofRequest(BaseModel):
    item: str = Field(..., description="Leaf value (record_hash)")
    root: str = Field(..., description="Merkle root")
    proof: list[dict[str, Any]] = Field(..., description="Proof steps: [{position, hash}]")


def _chain_hashes(token: str) -> list[str]:
    try:
        store = get_evidence_store()
    except SupabaseNotConfiguredError:
        raise HTTPException(
            status_code=503,
            detail="Evidence store not configured (SUPABASE_URL/KEY)",
        )
    records = sorted(
        (r for r in store.list_chain(token) if r.get("record_hash")),
        key=lambda r: int(r.get("chain_seq", 0)),
    )
    if not records:
        raise HTTPException(status_code=404, detail=f"No evidence chain for token {token}")
    return [str(r["record_hash"]) for r in records]


@router.post("/anchor")
def anchor_chain(req: AnchorRequest, request: Request) -> dict:
    """Kanıt zincirini Merkle köküne indirir ve çapalar (varsayılan yerel çapa)."""
    require_api_token(request)
    try:
        receipt = anchor_evidence_chain(
            [{"record_hash": h, "chain_seq": i} for i, h in enumerate(_chain_hashes(req.token))]
        )
    except AnchorError as exc:
        raise HTTPException(status_code=502, detail=f"Anchor failed: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Anchor error: {exc}")
    return receipt.to_dict()


@router.post("/proof")
def record_proof(req: ProofRequest, request: Request) -> dict:
    """Belirli bir kaydın dahil olma kanıtını (Merkle yolu) döner."""
    require_api_token(request)
    hashes = _chain_hashes(req.token)
    if req.index >= len(hashes):
        raise HTTPException(status_code=404, detail=f"Index {req.index} out of range")
    steps = merkle_proof(hashes, req.index)
    return {
        "root": merkle_root(hashes),
        "item": hashes[req.index],
        "proof": [{"position": s.position, "hash": s.hash} for s in steps],
    }


@router.post("/verify-proof")
def check_proof(req: VerifyProofRequest, request: Request) -> dict:
    """Kanıtı yalnızca kök + yolla doğrular; zincire erişim gerekmez."""
    require_api_token(request)
    try:
        steps = [ProofStep(position=s["position"], hash=s["hash"]) for s in req.proof]
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid proof step: {exc}")
    return {"valid": verify_proof(req.item, steps, req.root)}
