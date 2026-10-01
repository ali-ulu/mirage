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
    SupabaseNotConfiguredError,
    SupabaseOperationError,
)
from .siem import SiemError, export_token, get_siem_sink
from .llm import LLMConfigError, get_llm_provider, triage_beacon
from .agent import (
    AgentGuard,
    CanaryRegistry,
    GuardBlocked,
    apply_decoy_plan,
    evaluate_rules,
    get_agent_guard,
    install_agent_guard_middleware,
    install_agent_scan_middleware,
    plan_decoy_schema,
    render_canary,
    scan_text_for_leaks,
)
from .env import fail_fast_on_missing_env

# Production startup check — fail fast if env is missing
fail_fast_on_missing_env()

# ---------------------------------------------------------------------------
# Bağımlılıklar (tek kaynak: mirage.api.deps)
# ---------------------------------------------------------------------------
# Store/motor singleton'ları ve API auth burada TANIMLANMAZ; `api/deps.py`'de
# tutulur ve router'lar oradan beslenir. Aşağıdaki re-export'lar geriye dönük
# uyumluluk içindir (testler `server.reset_*` kancalarını kullanır).
from .api.deps import (  # noqa: E402
    get_canary_registry,
    get_evidence_store,
    get_honeypot_engine,
    get_registry,
    get_team_store,
    get_triage_store,
    require_api_token as _require_api_token,
    reset_canary_registry_for_testing,
    reset_evidence_store_for_testing,
    reset_honeypot_engine_for_testing,
    reset_registry_for_testing,
    reset_team_store_for_testing,
    reset_triage_store_for_testing,
)

app = FastAPI(
    title="MIRAGE Synthetic Data Engine",
    description="Statistically isomorphic synthetic data generator for deception infrastructure. No payload injection, no code execution on consumer machine.",
    version="0.4.0",
)

# Otomatik runtime tarama (opt-in): JSON yanıt gövdelerinde canary sızıntısı.
# MIRAGE_SCAN_MIDDLEWARE truthy değilse no-op.
install_agent_scan_middleware(app)

# Satır-içi ajan koruması (opt-in): /agent/proxy uçlarına GİDEN istek gövdelerini
# uygulamaya ulaşmadan önce tarar; ihlalde 422 (upstream'e iletilmez).
# MIRAGE_AGENT_GUARD truthy değilse no-op.
install_agent_guard_middleware(app)

# Modüler router'lar (yeni savunma modülleri: MCP gateway, RAG guard, deception,
# behavior, Merkle anchor, DLP). Tek app, çok router.
from .api.routes import register_routers  # noqa: E402

register_routers(app)


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
    team_id: Optional[str] = Field(None, description="Multi-tenant owner (team UUID)")


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


class CanaryIssueRequest(BaseModel):
    context: str = Field(
        ...,
        pattern="^(system_prompt|rag_document|agent_memory)$",
        description="Where the canary will be embedded",
    )
    label: str = Field("", description="Optional label (e.g. 'support-rag-v2')")
    style: str = Field("raw", pattern="^(raw|note)$", description="Rendering style")
    team_id: Optional[str] = Field(None, description="Multi-tenant owner (team UUID)")


class CanaryCheckRequest(BaseModel):
    text: str = Field(..., description="Text to scan for issued canary markers")
    token: Optional[str] = Field(None, description="Honeytoken UUID to attach the leak to (for triage ledger)")
    persist: bool = Field(False, description="Persist a triage record when a leak is found")
    chain_verified: Optional[bool] = Field(None, description="Evidence chain verification result, if known")
    team_id: Optional[str] = Field(None, description="Multi-tenant owner recorded on the triage record")


class ScanRule(BaseModel):
    name: str = Field(..., description="Rule name (e.g. 'aws_key')")
    pattern: str = Field(..., description="Regex to search for")
    severity: str = Field("low", pattern="^(low|medium|high|critical)$")
    description: str = Field("", description="Human-readable rule description")


class ScanRequest(BaseModel):
    text: str = Field(..., description="Agent output / log line / tool argument to scan")
    source: str = Field("", description="Optional source label (e.g. 'agent-output', 'tool-call')")
    rules: list[ScanRule] = Field(default_factory=list, description="Customer-defined regex rules")
    token: Optional[str] = Field(None, description="Honeytoken UUID to attach the leak to (for triage ledger)")
    persist: bool = Field(False, description="Persist a triage record when a canary leak is found")
    chain_verified: Optional[bool] = Field(None, description="Evidence chain verification result, if known")
    team_id: Optional[str] = Field(None, description="Multi-tenant owner recorded on the triage record")
    block: bool = Field(
        False,
        description="Giden (upstream) kapı modu: ihlalde 422 döndür (metin gönderilmesin)",
    )


class TeamMemberRequest(BaseModel):
    user_id: str = Field(..., description="User UUID (JWT `sub` claim)")
    team_id: str = Field(..., description="Team UUID")
    role: str = Field("member", pattern="^(owner|admin|member)$", description="Membership role")


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


@app.post("/agent/canary", status_code=201)
def issue_prompt_canary(req: CanaryIssueRequest, request: Request) -> dict:
    """
    Bir AI ajanı bağlamı için prompt-layer canary üretir. İşaret system
    prompt / RAG dokümanı / agent memory içine gömülür; sonradan başka bir
    yerde görünürse bağlamın sızdığı anlaşılır.
    """
    _require_api_token(request)
    registry = get_canary_registry()
    try:
        canary = registry.issue(req.context, label=req.label, team_id=req.team_id)
    except SupabaseOperationError as e:
        raise HTTPException(status_code=503, detail=f"Canary registry unavailable: {e}")
    payload = canary.to_dict()
    payload["rendered"] = render_canary(canary, style=req.style)
    return payload


@app.post("/agent/canary/check")
async def check_prompt_canary(req: CanaryCheckRequest, request: Request) -> dict:
    """
    Verilen metinde kayıtlı canary işaretlerini arar. Sızıntı bulunursa
    opsiyonel olarak triyajlanır (LLM veya sezgisel) ve `persist=True` +
    `token` verilmişse append-only triyaj defterine yazılır.
    """
    _require_api_token(request)
    registry = get_canary_registry()

    if registry.match(req.text) and req.persist and req.token:
        try:
            triage_store = get_triage_store()
        except SupabaseNotConfiguredError:
            raise HTTPException(
                status_code=503,
                detail="Triage ledger not configured (SUPABASE_URL/SERVICE_ROLE_KEY missing)",
            )
    else:
        triage_store = None

    try:
        provider = get_llm_provider()
    except LLMConfigError as e:
        raise HTTPException(status_code=503, detail=f"LLM misconfigured: {e}")

    try:
        evidence_store = get_evidence_store()
    except SupabaseNotConfiguredError:
        evidence_store = None

    try:
        return await scan_text_for_leaks(
            registry=registry,
            text=req.text,
            provider=provider,
            evidence_store=evidence_store,
            triage_store=triage_store,
            token=req.token,
            persist=req.persist,
            chain_verified=req.chain_verified,
            team_id=req.team_id,
        )
    except SupabaseOperationError:
        raise HTTPException(status_code=502, detail="Failed to persist triage record")


@app.post("/agent/scan")
async def scan_agent_output(req: ScanRequest, request: Request) -> dict:
    """
    Runtime tarama: ajan çıktısı / log / araç çağrısı metnini canary ve
    müşteri tanımlı kurallara göre tarar. Canary sızıntısı bulunursa
    `/agent/canary/check` ile aynı yoldan triyajlanır (LLM opsiyonel).
    """
    _require_api_token(request)
    registry = get_canary_registry()

    has_canary = bool(registry.match(req.text))
    if has_canary and req.persist and req.token:
        try:
            triage_store = get_triage_store()
        except SupabaseNotConfiguredError:
            raise HTTPException(
                status_code=503,
                detail="Triage ledger not configured (SUPABASE_URL/SERVICE_ROLE_KEY missing)",
            )
    else:
        triage_store = None

    try:
        provider = get_llm_provider()
    except LLMConfigError as e:
        raise HTTPException(status_code=503, detail=f"LLM misconfigured: {e}")

    try:
        evidence_store = get_evidence_store()
    except SupabaseNotConfiguredError:
        evidence_store = None

    try:
        leak = await scan_text_for_leaks(
            registry=registry,
            text=req.text,
            provider=provider,
            evidence_store=evidence_store,
            triage_store=triage_store,
            token=req.token,
            persist=req.persist,
            chain_verified=req.chain_verified,
            team_id=req.team_id,
        )
    except SupabaseOperationError:
        raise HTTPException(status_code=502, detail="Failed to persist triage record")

    findings = evaluate_rules(req.text, [r.model_dump() for r in req.rules])
    leak["rules"] = findings
    leak["rule_hits"] = len(findings)
    leak["source"] = req.source
    leak["clean"] = not leak["leaked"] and not findings

    # Giden (upstream) kapı modu: ihlal varsa 422 ile durdur — metin gönderilmez.
    if req.block and not leak["clean"]:
        raise HTTPException(status_code=422, detail=leak)
    return leak


class ProxyCallRequest(BaseModel):
    url: str = Field(..., description="Upstream target URL the agent wants to call")
    method: str = Field("POST", description="HTTP method")
    headers: dict[str, str] = Field(default_factory=dict, description="Outbound headers")
    body: Any = Field(None, description="Outbound body (scanned before the call is made)")
    rules: list[ScanRule] = Field(default_factory=list, description="Customer-defined regex rules")


class HoneypotCreateRequest(BaseModel):
    token: Optional[str] = Field(None, description="Honeytoken UUID to attach the session to")
    context: Optional[str] = Field(None, description="Context hint for the generated persona")


class HoneypotMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Attacker message to the honeypot")
    persist: bool = Field(False, description="Persist a triage record when a leak is caught")
    chain_verified: Optional[bool] = Field(None, description="Evidence chain verification result, if known")
    team_id: Optional[str] = Field(None, description="Multi-tenant owner recorded on the triage record")


@app.post("/agent/proxy")
async def agent_proxy(req: ProxyCallRequest, request: Request) -> dict:
    """
    Ajanın giden API çağrısı için satır-içi kapı (inline guard).

    Gövde, upstream'e GÖNDERİLMEDEN önce canary + müşteri regex kurallarına göre
    taranır. `MIRAGE_AGENT_GUARD` truthy ise ihlal `GuardBlocked` ile 422 döner ve
    çağrı hiç yapılmaz; aksi halde yalnızca raporlanır (`enforced=false`).

    Bu uç, gerçek giden çağrıyı MIRAGE yapmaz (SSRF yüzeyi açmamak için); kararı
    uygulayan istemcidir. Amaç, ajanın dış dünyaya dokunduğu sınırda deterministik
    bir engelleme/yakalama noktası sağlamaktır.
    """
    _require_api_token(request)
    guard: AgentGuard = get_agent_guard(rules=[r.model_dump() for r in req.rules])
    text = req.body if isinstance(req.body, str) else json.dumps(req.body, ensure_ascii=False)
    try:
        report = guard.guard_api_call(text, surface="api-proxy")
    except GuardBlocked as blocked:
        raise HTTPException(status_code=422, detail=blocked.leak)
    return {
        "enforced": guard.enforce,
        "clean": report.get("clean", True),
        "blocked": False,
        "url": req.url,
        "method": req.method,
        "leak": report,
    }


# ---------------------------------------------------------------------------
# Dinamik LLM honeypot (deception — VelLMes/DECEIVE parity)
# ---------------------------------------------------------------------------
@app.post("/honeypot/session", status_code=201)
async def create_honeypot_session(req: HoneypotCreateRequest, request: Request) -> dict:
    """
    Yeni bir deception oturumu açar. Persona LLM ile üretilir (opsiyonel);
    LLM yoksa deterministik uydurma personaya düşülür. Persona sırrına bir
    canary işlenir; saldırgan sızdırırsa yakalanır.
    """
    _require_api_token(request)
    try:
        provider = get_llm_provider()
    except LLMConfigError as e:
        raise HTTPException(status_code=503, detail=f"LLM misconfigured: {e}")
    engine = get_honeypot_engine()
    session = await engine.create_session(token=req.token, context=req.context, provider=provider)
    return session.to_dict(include_transcript=False)


@app.post("/honeypot/session/{session_id}/message")
async def honeypot_message(
    session_id: str, req: HoneypotMessageRequest, request: Request
) -> dict:
    """
    Saldırgan mesajına deception yanıtı üretir ve canary sızıntısını yakalar.

    Sızıntı yakalanırsa ve `persist` ise triyaj defterine yazılır (kanıt zinciri
    doğrulaması ile birlikte). 404: oturum bulunamadı.
    """
    _require_api_token(request)
    engine = get_honeypot_engine()
    session = engine.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Honeypot session not found")

    try:
        provider = get_llm_provider()
    except LLMConfigError as e:
        raise HTTPException(status_code=503, detail=f"LLM misconfigured: {e}")

    turn = await engine.respond(session, req.message, provider=provider)

    triage = None
    if turn.leaked and req.persist and req.token:
        try:
            triage_store = get_triage_store()
        except SupabaseNotConfiguredError:
            raise HTTPException(
                status_code=503,
                detail="Triage ledger not configured (SUPABASE_URL/SERVICE_ROLE_KEY missing)",
            )
        try:
            evidence_store = get_evidence_store()
        except SupabaseNotConfiguredError:
            evidence_store = None
        try:
            triage = await scan_text_for_leaks(
                registry=engine.registry,
                text=req.message,
                provider=provider,
                evidence_store=evidence_store,
                triage_store=triage_store,
                token=req.token,
                persist=True,
                chain_verified=req.chain_verified,
                team_id=req.team_id,
            )
        except SupabaseOperationError:
            raise HTTPException(status_code=502, detail="Failed to persist triage record")

    return {
        "session_id": session_id,
        "reply": turn.reply,
        "leaked": turn.leaked,
        "canary_hits": turn.canary_hits,
        "triage": triage,
    }


# ---------------------------------------------------------------------------
# Team membership routes (multi-tenant yönetim — service_role)
# ---------------------------------------------------------------------------
@app.post("/team/members", status_code=201)
def add_team_member(req: TeamMemberRequest, request: Request) -> dict:
    """
    Bir kullanıcıyı takıma ekler (rol ile). Aynı çift varsa rol güncellenir.
    Bu uç service_role ile çalışır; 0008 RLS `authenticated` istemcilerin
    yalnızca üye oldukları takımları görmesini sağlar.
    """
    _require_api_token(request)
    try:
        store = get_team_store()
    except SupabaseNotConfiguredError:
        raise HTTPException(status_code=503, detail="Team store not configured (Supabase missing)")
    try:
        member = store.add(user_id=req.user_id, team_id=req.team_id, role=req.role)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except SupabaseOperationError:
        raise HTTPException(status_code=502, detail="Failed to write team membership")
    return member.to_dict()


@app.get("/team/{team_id}/members")
def list_team_members(team_id: str, request: Request) -> dict:
    """Bir takımın üyelerini listeler."""
    _require_api_token(request)
    try:
        store = get_team_store()
    except SupabaseNotConfiguredError:
        raise HTTPException(status_code=503, detail="Team store not configured (Supabase missing)")
    try:
        members = store.list_for_team(team_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"team_id": team_id, "count": len(members), "members": [m.to_dict() for m in members]}


@app.get("/team/{team_id}/members/{user_id}")
def get_team_member(team_id: str, user_id: str, request: Request) -> dict:
    """Bir kullanıcının takımdaki rolünü döndürür."""
    _require_api_token(request)
    try:
        store = get_team_store()
    except SupabaseNotConfiguredError:
        raise HTTPException(status_code=503, detail="Team store not configured (Supabase missing)")
    try:
        role = store.get_role(user_id=user_id, team_id=team_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if role is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    return {"user_id": user_id, "team_id": team_id, "role": role}


@app.delete("/team/{team_id}/members/{user_id}")
def remove_team_member(team_id: str, user_id: str, request: Request) -> dict:
    """Bir üyeliği kaldırır."""
    _require_api_token(request)
    try:
        store = get_team_store()
    except SupabaseNotConfiguredError:
        raise HTTPException(status_code=503, detail="Team store not configured (Supabase missing)")
    try:
        removed = store.remove(user_id=user_id, team_id=team_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except SupabaseOperationError:
        raise HTTPException(status_code=502, detail="Failed to remove team membership")
    if removed == 0:
        raise HTTPException(status_code=404, detail="Membership not found")
    return {"removed": removed}


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
        record = registry.issue(
            df, base_url=req.base_url, label=req.label, team_id=req.team_id
        )
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


# ---------------------------------------------------------------------------
# SIEM/SOAR export (kanıt + triyaj → Splunk HEC / webhook)
# ---------------------------------------------------------------------------
@app.post("/siem/export/{token}")
async def export_to_siem(token: str, request: Request) -> dict:
    """
    Bir token'ın kanıt zincirini + triyaj kayıtlarını normalize SIEM olaylarına
    çevirip yapılandırılmış sink'e gönderir (`MIRAGE_SIEM_SINK`).

    Kanıt zinciri önce doğrulanır; `chain_verified` olaylara işlenir. Sink
    yapılandırılmamışsa 503, gönderim başarısızsa 502 döner.
    """
    _require_api_token(request)
    try:
        sink = get_siem_sink()
    except SiemError as e:
        raise HTTPException(status_code=503, detail=f"SIEM sink misconfigured: {e}")
    if sink is None:
        raise HTTPException(
            status_code=503,
            detail="SIEM export not configured (set MIRAGE_SIEM_SINK)",
        )
    try:
        evidence_store = get_evidence_store()
    except SupabaseNotConfiguredError:
        evidence_store = None
    try:
        triage_store = get_triage_store()
    except SupabaseNotConfiguredError:
        triage_store = None
    try:
        return await export_token(
            token=token,
            evidence_store=evidence_store,
            triage_store=triage_store,
            sink=sink,
        )
    except SiemError as e:
        raise HTTPException(status_code=502, detail=f"SIEM delivery failed: {e}")
