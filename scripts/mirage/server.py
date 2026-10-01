"""
MIRAGE FastAPI service — Synthetic data engine for deception infrastructure.

POST /synthesize
    Body: {"rows": N, "data": [ {col: val, ...}, ... ]}
    Returns: CSV synthetic data (or JSON)

POST /profile
    Body: {"data": [ ... ]}
    Returns: per-column profile summary (no synthetic data)

POST /honeytoken
    Body: {"data": [...], "base_url": "https://beacon.example/track", "label": "..."}
    Returns: XLSX file with embedded passive tracking URL.

    Security: This endpoint NEVER produces payloads that execute code on the
    consumer machine. Only an HTTP GET is triggered when the file is opened
    by an office application.

GET  /health
"""
from __future__ import annotations

import io
import json
import os
from typing import Any, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from .synthesizer import MirageSynthesizer
from .honeytoken import inject_honeytoken
from .supabase_registry import (
    SupabaseHoneytokenRegistry,
    SupabaseNotConfiguredError,
    SupabaseOperationError,
)
from .triage_store import BeaconTriageStore
from .evidence_store import EvidenceChainStore
from .llm import LLMConfigError, get_llm_provider, triage_beacon
from .agent import apply_decoy_plan, plan_decoy_schema
from .env import fail_fast_on_missing_env, is_production

# Production startup check — fail fast if env is missing
fail_fast_on_missing_env()

# Production registry: Supabase-backed (persistent across restarts).
# Lazy-initialized so the module can be imported without SUPABASE_URL set
# (e.g. for unit tests of unrelated endpoints).
_REGISTRY: Optional[SupabaseHoneytokenRegistry] = None


def get_registry() -> SupabaseHoneytokenRegistry:
    """Lazy singleton — fails fast if Supabase env is missing."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = SupabaseHoneytokenRegistry()  # raises if not configured
    return _REGISTRY


def reset_registry_for_testing(client=None) -> None:
    """Test hook — inject a mock client or reset to None."""
    global _REGISTRY
    if client is not None:
        _REGISTRY = SupabaseHoneytokenRegistry(client=client)
    else:
        _REGISTRY = None


# Beacon triyaj defteri (kanıt zincirine bağlı, ayrı append-only store).
_TRIAGE_STORE: Optional[BeaconTriageStore] = None


def get_triage_store() -> BeaconTriageStore:
    """Lazy singleton — Supabase env yoksa SupabaseNotConfiguredError."""
    global _TRIAGE_STORE
    if _TRIAGE_STORE is None:
        _TRIAGE_STORE = BeaconTriageStore()
    return _TRIAGE_STORE


def reset_triage_store_for_testing(client=None) -> None:
    """Test hook — inject a mock client or reset to None."""
    global _TRIAGE_STORE
    if client is not None:
        _TRIAGE_STORE = BeaconTriageStore(client=client)
    else:
        _TRIAGE_STORE = None


# Kanıt zinciri okuma/doğrulama deposu.
_EVIDENCE_STORE: Optional[EvidenceChainStore] = None


def get_evidence_store() -> EvidenceChainStore:
    """Lazy singleton — Supabase env yoksa SupabaseNotConfiguredError."""
    global _EVIDENCE_STORE
    if _EVIDENCE_STORE is None:
        _EVIDENCE_STORE = EvidenceChainStore()
    return _EVIDENCE_STORE


def reset_evidence_store_for_testing(client=None) -> None:
    """Test hook — inject a mock client or reset to None."""
    global _EVIDENCE_STORE
    if client is not None:
        _EVIDENCE_STORE = EvidenceChainStore(client=client)
    else:
        _EVIDENCE_STORE = None


app = FastAPI(
    title="MIRAGE Synthetic Data Engine",
    description="Statistically isomorphic synthetic data generator for deception infrastructure. No payload injection, no code execution on consumer machine.",
    version="0.4.0",
)




# ---------------------------------------------------------------------------
# API auth
# ---------------------------------------------------------------------------
def _require_api_token(request: Request) -> None:
    """Protect state-changing/data-export endpoints when MIRAGE_API_TOKEN is set.

    Development remains frictionless if no token is configured. Production must
    configure MIRAGE_API_TOKEN; otherwise sensitive endpoints fail closed.
    Accepted headers: Authorization: Bearer <token> or X-API-Key: <token>.
    """
    expected = os.environ.get("MIRAGE_API_TOKEN")
    if not expected:
        if is_production():
            raise HTTPException(status_code=503, detail="MIRAGE_API_TOKEN not configured")
        return

    authorization = request.headers.get("authorization", "")
    provided = request.headers.get("x-api-key") or authorization.removeprefix("Bearer ").strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SynthesizeRequest(BaseModel):
    rows: int = Field(1000, gt=0, le=1_000_000, description="Number of synthetic rows to generate")
    data: list[dict[str, Any]] = Field(..., min_length=1, description="Real data sample (JSON array of objects)")
    seed: Optional[int] = Field(None, description="Random seed for reproducibility")
    format: str = Field("csv", pattern="^(csv|json)$", description="Output format")


class ProfileRequest(BaseModel):
    data: list[dict[str, Any]] = Field(..., min_length=1)


class HoneytokenRequest(BaseModel):
    data: list[dict[str, Any]] = Field(..., min_length=1, description="Data to package into the XLSX")
    base_url: str = Field(..., description="Tracking URL base (e.g. https://beacon.example/track)")
    label: str = Field("", description="Optional label for the honeytoken (e.g. 'Q4-finance-export')")
    sheet_name: str = Field("Sheet", description="Sheet name in the XLSX")


class HoneytokenLookupRequest(BaseModel):
    token: str = Field(..., description="Token to look up in the registry")


class TriageRequest(BaseModel):
    token: str = Field(..., description="Honeytoken token (UUID) that triggered")
    event: dict[str, Any] = Field(
        default_factory=dict,
        description="Beacon event fields (user_agent, distinct_ips, opener_app, ...)",
    )
    chain_seq: Optional[int] = Field(None, description="Related evidence chain_seq, if known")
    chain_verified: Optional[bool] = Field(None, description="Evidence chain verification result")
    persist: bool = Field(True, description="Persist the triage record to the append-only ledger")


class PlanRequest(BaseModel):
    data: list[dict[str, Any]] = Field(..., min_length=1, description="Schema sample (JSON array of objects)")


class AnonymizeRequest(BaseModel):
    data: list[dict[str, Any]] = Field(..., min_length=1, description="Table to anonymize (JSON array of objects)")
    seed: Optional[int] = Field(None, description="Random seed for reproducible decoy generation")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine": "mirage", "version": app.version}


@app.post("/profile")
def profile(req: ProfileRequest, request: Request) -> dict:
    _require_api_token(request)
    try:
        df = pd.DataFrame(req.data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot parse data: {e}")

    synth = MirageSynthesizer().fit(df)
    return {
        "columns": [
            {
                "name": p.name,
                "type": p.col_type,
                "format_kind": p.format_kind,
                "null_prob": round(p.null_prob, 4),
                "categories": (p.categories.tolist() if p.categories is not None and len(p.categories) <= 50 else None),
            }
            for p in synth.profiles
        ],
        "numeric_block": [synth.column_order[i] for i in synth.numeric_indices],
    }


@app.post("/synthesize")
def synthesize(req: SynthesizeRequest, request: Request):
    _require_api_token(request)
    try:
        df = pd.DataFrame(req.data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot parse data: {e}")

    synth = MirageSynthesizer(seed=req.seed).fit(df)
    result = synth.synthesize(req.rows)

    meta = {
        "rows": req.rows,
        "elapsed_ms": round(result.elapsed_ms, 3),
        "ms_per_row": round(result.ms_per_row, 5),
        "budget_ms_per_row": 0.05,
        "within_budget": result.ms_per_row <= 0.05,
    }

    if req.format == "json":
        return JSONResponse(
            content={"meta": meta, "data": json.loads(result.df.to_json(orient="records"))}
        )
    # CSV
    buf = io.StringIO()
    result.df.to_csv(buf, index=False)
    buf.seek(0)
    headers = {
        "X-MIRAGE-Elapsed-MS": str(meta["elapsed_ms"]),
        "X-MIRAGE-MS-Per-Row": str(meta["ms_per_row"]),
        "X-MIRAGE-Within-Budget": str(meta["within_budget"]),
    }
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Agent routes (Planner Agent — decoy planlama)
# ---------------------------------------------------------------------------
@app.post("/agent/plan")
async def agent_plan(req: PlanRequest, request: Request) -> dict:
    """
    Bir şema örneği için decoy planı üretir (hangi kolonlar sentetik tuzak
    verisiyle değiştirilecek, hangileri korunacak).

    Planlama opsiyonel LLM ile üretilir; yapılandırılmamışsa deterministik
    sezgisel yola düşülür. Kimlik/anahtar kolonları asla decoy yapılmaz.
    """
    _require_api_token(request)
    try:
        df = pd.DataFrame(req.data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot parse data: {e}")

    try:
        provider = get_llm_provider()
    except LLMConfigError as e:
        raise HTTPException(status_code=503, detail=f"LLM misconfigured: {e}")

    plan = await plan_decoy_schema(df, provider=provider)
    return plan.to_dict()


@app.post("/agent/anonymize")
async def agent_anonymize(req: AnonymizeRequest, request: Request) -> dict:
    """
    Tabloyu plana göre anonimleştirir: decoy kolonlar sentetik veriyle
    değiştirilir, korunacak kolonlar aynen kalır. Satır sayısı ve kolon sırası
    korunur. `keep` kolonlar çıktıya dahil edilir; böylece çağıran, korunan
    alanların değişmediğini doğrulayabilir.
    """
    _require_api_token(request)
    try:
        df = pd.DataFrame(req.data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot parse data: {e}")

    try:
        provider = get_llm_provider()
    except LLMConfigError as e:
        raise HTTPException(status_code=503, detail=f"LLM misconfigured: {e}")

    plan = await plan_decoy_schema(df, provider=provider)
    decoyed = apply_decoy_plan(df, plan, seed=req.seed)
    return {
        "source": plan.source,
        "strategy": plan.strategy,
        "decoy_columns": plan.decoy_columns,
        "kept_columns": plan.kept_columns,
        "rows": len(decoyed),
        "data": json.loads(decoyed.to_json(orient="records")),
    }


# ---------------------------------------------------------------------------
# Honeytoken routes (Task 02 — production)
# ---------------------------------------------------------------------------
@app.post("/honeytoken", status_code=201)
def create_honeytoken(req: HoneytokenRequest, request: Request):
    _require_api_token(request)
    """
    Generate an XLSX file from the provided data, with a passive tracking URL
    embedded in its XML structure. When the file is opened by an office
    application (Excel, LibreOffice Calc, etc.), the office app issues a
    single HTTP GET to the tracking URL. No code is executed on the consumer
    machine — only a network request.

    The token is persisted to Supabase `honeytokens` table (RLS-protected)
    so it survives server restarts.
    """
    try:
        df = pd.DataFrame(req.data)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Cannot parse data payload")

    # Validate base_url — must be http(s)
    if not (req.base_url.startswith("http://") or req.base_url.startswith("https://")):
        raise HTTPException(
            status_code=400,
            detail="base_url must start with http:// or https://",
        )

    # Issue token via Supabase-backed registry (persistent)
    try:
        registry = get_registry()
        record = registry.issue(df, base_url=req.base_url, label=req.label)
    except SupabaseNotConfiguredError:
        # Fail fast with actionable error — do NOT swallow config errors
        raise HTTPException(
            status_code=503,
            detail="Honeytoken registry not configured (SUPABASE_URL/SERVICE_ROLE_KEY missing)",
        )
    except SupabaseOperationError as e:
        # DB error — log internally, return generic message to client
        # (no internals leaked)
        raise HTTPException(
            status_code=502,
            detail="Failed to persist honeytoken metadata",
        )

    xlsx_bytes = inject_honeytoken(
        df,
        base_url=req.base_url,
        sheet_name=req.sheet_name,
        token=record.token,
    )

    headers = {
        "X-MIRAGE-Token": record.token,
        "X-MIRAGE-Tracking-URL": record.full_url,
        "X-MIRAGE-Label": record.label,
        "X-MIRAGE-Created-At": record.created_at,
        "Content-Disposition": f'attachment; filename="mirage_{record.token[:8]}.xlsx"',
    }
    return StreamingResponse(
        iter([xlsx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
        status_code=201,
    )


@app.post("/honeytoken/lookup")
def lookup_honeytoken(req: HoneytokenLookupRequest, request: Request):
    _require_api_token(request)
    """Look up a previously-issued honeytoken by its token."""
    try:
        registry = get_registry()
    except SupabaseNotConfiguredError:
        raise HTTPException(
            status_code=503,
            detail="Registry not configured",
        )
    record = registry.lookup(req.token)
    if record is None:
        raise HTTPException(status_code=404, detail="Token not found")
    return record.to_dict()


@app.get("/honeytokens")
def list_honeytokens(request: Request):
    _require_api_token(request)
    """List all issued honeytokens (active only, by default)."""
    try:
        registry = get_registry()
    except SupabaseNotConfiguredError:
        raise HTTPException(
            status_code=503,
            detail="Registry not configured",
        )
    records = registry.list_active(limit=100)
    return {
        "count": len(records),
        "records": [r.to_dict() for r in records],
    }


# ---------------------------------------------------------------------------
# Beacon triage routes (P0 follow-up — kanıt zincirine bağlı triyaj kaydı)
# ---------------------------------------------------------------------------
@app.post("/beacon/triage", status_code=201)
async def create_beacon_triage(req: TriageRequest, request: Request) -> dict:
    """
    Bir beacon olayını triyaj eder ve sonucu append-only deftere yazar.

    Triyaj opsiyonel LLM (OpenAI/Anthropic) ile üretilir; yapılandırılmamışsa
    deterministik sezgisel yola düşülür. Opsiyonel LLM katmanı çekirdeği
    bozmaz: her durumda geçerli bir sonuç döner.
    """
    _require_api_token(request)

    try:
        provider = get_llm_provider()
    except LLMConfigError as e:
        raise HTTPException(status_code=503, detail=f"LLM misconfigured: {e}")

    result = await triage_beacon(
        req.event,
        provider=provider,
        chain_ok=req.chain_verified,
    )

    model = None
    if provider is not None and result.source.startswith("llm:"):
        model = getattr(provider, "_model", None)

    record = None
    if req.persist:
        try:
            store = get_triage_store()
        except SupabaseNotConfiguredError:
            raise HTTPException(
                status_code=503,
                detail="Triage ledger not configured (SUPABASE_URL/SERVICE_ROLE_KEY missing)",
            )
        except SupabaseOperationError:
            raise HTTPException(status_code=502, detail="Failed to persist triage record")
        try:
            record = store.save(req.token, result, chain_seq=req.chain_seq, model=model)
        except SupabaseOperationError:
            raise HTTPException(status_code=502, detail="Failed to persist triage record")

    payload = result.to_dict()
    payload["token"] = req.token
    payload["chain_seq"] = req.chain_seq
    payload["model"] = model
    payload["persisted"] = record is not None
    return payload


@app.get("/beacon/triage/{token}")
def list_beacon_triage(token: str, request: Request) -> dict:
    """Bir token için triyaj kayıtlarını (en yeni önce) döndürür."""
    _require_api_token(request)
    try:
        store = get_triage_store()
    except SupabaseNotConfiguredError:
        raise HTTPException(status_code=503, detail="Triage ledger not configured")
    records = store.list_for_token(token, limit=50)
    return {
        "count": len(records),
        "records": [r.to_dict() for r in records],
    }


# ---------------------------------------------------------------------------
# Evidence chain read + verify routes (P0 follow-up — kanıt doğrulama API'si)
# ---------------------------------------------------------------------------
@app.get("/beacon/evidence/{token}")
def list_evidence_chain(token: str, request: Request) -> dict:
    """Bir token'a ait kanıt kayıtlarını (chain_seq sırasıyla) döndürür."""
    _require_api_token(request)
    try:
        store = get_evidence_store()
    except SupabaseNotConfiguredError:
        raise HTTPException(status_code=503, detail="Evidence store not configured")
    try:
        records = store.list_chain(token)
    except SupabaseOperationError:
        raise HTTPException(status_code=502, detail="Failed to read evidence chain")
    return {"count": len(records), "records": records}


@app.get("/beacon/evidence/{token}/verify")
def verify_evidence_chain(token: str, request: Request) -> dict:
    """
    Bir token'ın kanıt zincirini bağımsız olarak doğrular (hash zinciri + HMAC).

    Anahtar yoksa fail-closed: `ok=False, reason='signing key unavailable'`.
    """
    _require_api_token(request)
    try:
        store = get_evidence_store()
    except SupabaseNotConfiguredError:
        raise HTTPException(status_code=503, detail="Evidence store not configured")
    try:
        return store.verify(token)
    except SupabaseOperationError:
        raise HTTPException(status_code=502, detail="Failed to verify evidence chain")
