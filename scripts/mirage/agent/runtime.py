"""
MIRAGE — Runtime tarama katmanı (ajan çıktısı / log / araç çağrısı).

Canary kontrolünü manuel uçtan otomatik runtime'a taşır: bir ajanın çıktısı,
log satırı veya araç çağrısı argümanı bu katmandan geçirilir. İki sinyal
birlikte değerlendirilir:

  1. Canary sızıntısı — kayıtlı bir `[[MIRAGE-CANARY:...]]` işareti görülürse
     bu bir sızıntıdır; beacon gibi triyajlanır ve (istenirse) append-only
     deftere yazılır. Ortak orkestrasyon `scan_text_for_leaks`'te tutulur;
     `/agent/canary/check` ile aynı kod yolu (tek kaynak, DRY).
  2. Deterministik kurallar — müşteri tanımlı regex'ler (ör. API anahtarı,
     "system prompt" sızıntı ifadesi). LLM gerekmez.

Tasarım: çekirdek saf/deterministik kalır; LLM opsiyoneldir ve her hata
fail-safe'tir (kural hatası taramayı durdurmaz).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ..llm.provider import LLMProvider
from ..supabase_registry import SupabaseNotConfiguredError, SupabaseOperationError
from .canary_evidence import resolve_chain_binding
from .canary_triage import triage_canary

VALID_SEVERITIES = ("low", "medium", "high", "critical")


async def scan_text_for_leaks(
    *,
    registry: Any,
    text: str,
    provider: Optional[LLMProvider] = None,
    evidence_store: Optional[Any] = None,
    triage_store: Optional[Any] = None,
    token: Optional[str] = None,
    persist: bool = False,
    chain_verified: Optional[bool] = None,
    team_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Metinde kayıtlı canary işaretlerini arar; bulunursa triyajlar ve istenirse
    append-only triyaj defterine yazar. `/agent/canary/check` ile aynı sözleşme.

    Raises:
        SupabaseNotConfiguredError: persist istendi ama triyaj defteri yok.
        SupabaseOperationError: defter yazımı başarısız.
    """
    matches = registry.match(text)
    payload: dict[str, Any] = {
        "leaked": bool(matches),
        "count": len(matches),
        "canaries": [c.to_dict() for c in matches],
    }
    if not matches:
        return payload

    binding: dict[str, Any] = {"linked": False, "chain_seq": None, "chain_verified": None, "reason": None}
    if token:
        binding = resolve_chain_binding(evidence_store, token)
    chain_ok = chain_verified if chain_verified is not None else binding["chain_verified"]

    leak = {
        "count": len(matches),
        "contexts": sorted({c.context for c in matches}),
        "canaries": [c.to_dict() for c in matches],
        "chain_seq": binding["chain_seq"],
    }
    result = await triage_canary(leak, provider=provider, chain_ok=chain_ok)

    model = None
    if provider is not None and result.source.startswith("llm:"):
        model = getattr(provider, "_model", None)

    persisted = False
    if persist and token:
        if triage_store is None:
            raise SupabaseNotConfiguredError(
                "Triage ledger not configured (SUPABASE_URL/SERVICE_ROLE_KEY missing)"
            )
        triage_store.save(
            token, result, chain_seq=binding["chain_seq"], model=model, team_id=team_id
        )
        persisted = True

    payload["triage"] = result.to_dict()
    payload["chain_seq"] = binding["chain_seq"]
    payload["chain_linked"] = binding["linked"]
    payload["model"] = model
    payload["persisted"] = persisted
    return payload


def evaluate_rules(text: str, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Müşteri tanımlı regex kurallarını uygular. Her eşleşen kural bir bulgu
    döndürür. Bozuk regex fail-safe olarak atlanır (tarama durmaz).
    """
    findings: list[dict[str, Any]] = []
    for rule in rules or []:
        pattern = rule.get("pattern")
        if not pattern:
            continue
        try:
            match = re.search(pattern, text or "")
        except re.error:
            findings.append(
                {"name": rule.get("name", ""), "severity": rule.get("severity", "low"),
                 "description": rule.get("description", ""), "error": "invalid regex"}
            )
            continue
        if match:
            findings.append(
                {
                    "name": rule.get("name", ""),
                    "severity": rule.get("severity", "low"),
                    "description": rule.get("description", ""),
                    "match": match.group(0)[:200],
                }
            )
    return findings


__all__ = ["scan_text_for_leaks", "evaluate_rules", "VALID_SEVERITIES", "SupabaseOperationError"]
