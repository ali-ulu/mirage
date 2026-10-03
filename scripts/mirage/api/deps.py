"""
MIRAGE API — bağımlılıklar ve paylaşılan yardımcılar.

Router'lar buradan beslenir. Tasarım ilkeleri:
  - **Döngüsellik yok:** Bu modül `mirage.server`'ı import ETMEZ. Store'ları ve
    motorları kendi lazy singleton'larında tutar; `server.py` bunları kullanır.
  - **Enjekte edilebilirlik:** Testler `reset_*` kancalarıyla sahte istemci
    verir; üretimde Supabase env'inden kurulur.
  - **Fail-safe:** Opsiyonel modüller (LLM, Supabase) yoksa deterministik
    davranışa düşer; API çökmez.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException, Request

from ..canary_store import SupabaseCanaryRegistry
from ..env import is_production
from ..evidence_store import EvidenceChainStore
from ..honeypot import HoneypotEngine
from ..supabase_registry import (
    SupabaseHoneytokenRegistry,
    SupabaseNotConfiguredError,
)
from ..team_store import TeamMembershipStore
from ..triage_store import BeaconTriageStore
from ..deception import DeceptionOrchestrator
from ..mcp_gateway import MCPGateway, default_policy_from_env
from ..mcp_audit_store import MCPAuditStore
from ..agent import CanaryRegistry

# ---------------------------------------------------------------------------
# API auth
# ---------------------------------------------------------------------------
def require_api_token(request: Request) -> None:
    """
    Veri-değiştiren/dışa-aktaran uçları korur (`MIRAGE_API_TOKEN`).

    Token yoksa: üretimde 503 (fail-closed), geliştirmede serbest.
    Kabul edilen başlıklar: `Authorization: Bearer <t>` veya `X-API-Key: <t>`.
    """
    import os

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
# Store / engine singletons
# ---------------------------------------------------------------------------
_REGISTRY: Optional[SupabaseHoneytokenRegistry] = None
_CANARY_REGISTRY: Optional[Any] = None
_TRIAGE_STORE: Optional[BeaconTriageStore] = None
_EVIDENCE_STORE: Optional[EvidenceChainStore] = None
_TEAM_STORE: Optional[TeamMembershipStore] = None
_HONEYPOT_ENGINE: Optional[HoneypotEngine] = None


def get_registry() -> SupabaseHoneytokenRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = SupabaseHoneytokenRegistry()  # raises if not configured
    return _REGISTRY


def reset_registry_for_testing(client=None) -> None:
    global _REGISTRY
    _REGISTRY = SupabaseHoneytokenRegistry(client=client) if client is not None else None


def get_canary_registry():
    """Supabase varsa kalıcı, yoksa in-memory registry (fail-safe)."""
    global _CANARY_REGISTRY
    if _CANARY_REGISTRY is None:
        try:
            _CANARY_REGISTRY = SupabaseCanaryRegistry()
        except SupabaseNotConfiguredError:
            _CANARY_REGISTRY = CanaryRegistry()
    return _CANARY_REGISTRY


def reset_canary_registry_for_testing(client=None) -> None:
    global _CANARY_REGISTRY
    _CANARY_REGISTRY = SupabaseCanaryRegistry(client=client) if client is not None else None


def get_triage_store() -> BeaconTriageStore:
    global _TRIAGE_STORE
    if _TRIAGE_STORE is None:
        _TRIAGE_STORE = BeaconTriageStore()
    return _TRIAGE_STORE


def reset_triage_store_for_testing(client=None) -> None:
    global _TRIAGE_STORE
    _TRIAGE_STORE = BeaconTriageStore(client=client) if client is not None else None


def get_evidence_store() -> EvidenceChainStore:
    global _EVIDENCE_STORE
    if _EVIDENCE_STORE is None:
        _EVIDENCE_STORE = EvidenceChainStore()
    return _EVIDENCE_STORE


def reset_evidence_store_for_testing(client=None) -> None:
    global _EVIDENCE_STORE
    _EVIDENCE_STORE = EvidenceChainStore(client=client) if client is not None else None


def get_team_store() -> TeamMembershipStore:
    global _TEAM_STORE
    if _TEAM_STORE is None:
        _TEAM_STORE = TeamMembershipStore()
    return _TEAM_STORE


def reset_team_store_for_testing(client=None) -> None:
    global _TEAM_STORE
    _TEAM_STORE = TeamMembershipStore(client=client) if client is not None else None


def get_honeypot_engine() -> HoneypotEngine:
    global _HONEYPOT_ENGINE
    if _HONEYPOT_ENGINE is None:
        _HONEYPOT_ENGINE = HoneypotEngine(registry=get_canary_registry())
    return _HONEYPOT_ENGINE


def reset_honeypot_engine_for_testing() -> None:
    global _HONEYPOT_ENGINE
    _HONEYPOT_ENGINE = None


# MCP gateway (denetim günlüğü süreç-içi tutulur → tek singleton olmalı).
_MCP_GATEWAY: Optional[MCPGateway] = None


def get_mcp_gateway() -> MCPGateway:
    global _MCP_GATEWAY
    if _MCP_GATEWAY is None:
        # Denetim kaydını kalıcı tabloya da yaz. Supabase yapılandırılmamışsa
        # (yerel demo, test) gateway yine de çalışır — sink yoktur, kararlar
        # yalnızca bellekteki audit_log'da tutulur (eski davranış).
        sink = None
        try:
            sink = MCPAuditStore.as_sink().save_entry
        except SupabaseNotConfiguredError:
            sink = None
        _MCP_GATEWAY = MCPGateway(
            policy=default_policy_from_env(),
            audit_sink=sink,
        )
    return _MCP_GATEWAY


def reset_mcp_gateway_for_testing(gateway: Optional[MCPGateway] = None) -> None:
    global _MCP_GATEWAY
    _MCP_GATEWAY = gateway


# Otonom deception orkestratörü (honeypot motorunu paylaşır).
_DECEPTION: Optional[DeceptionOrchestrator] = None


def get_deception_orchestrator() -> DeceptionOrchestrator:
    global _DECEPTION
    if _DECEPTION is None:
        _DECEPTION = DeceptionOrchestrator(engine=get_honeypot_engine())
    return _DECEPTION


def reset_deception_orchestrator_for_testing(
    orchestrator: Optional[DeceptionOrchestrator] = None,
) -> None:
    global _DECEPTION
    _DECEPTION = orchestrator


__all__ = [
    "require_api_token",
    "get_registry",
    "reset_registry_for_testing",
    "get_canary_registry",
    "reset_canary_registry_for_testing",
    "get_triage_store",
    "reset_triage_store_for_testing",
    "get_evidence_store",
    "reset_evidence_store_for_testing",
    "get_team_store",
    "reset_team_store_for_testing",
    "get_honeypot_engine",
    "reset_honeypot_engine_for_testing",
    "get_mcp_gateway",
    "reset_mcp_gateway_for_testing",
    "get_deception_orchestrator",
    "reset_deception_orchestrator_for_testing",
]
