"""
MIRAGE — Gerçek LLM uçtan uca smoke (opt-in).

`test_llm_smoke.py` triyaj yollarını çağırır; bu dosya **daha güçlü** bir
sözleşme doğrular:

  1. Hibrit sağlayıcı seçimi: `MIRAGE_LLM_PROVIDER=openai|anthropic` doğru
     somut sağlayıcıyı kurar (ağ gerekmez).
  2. Sağlayıcı gerçekten yanıt verir (canlı API çağrısı).
  3. Uçtan uca: canary sızıntısı → `scan_text_for_leaks` → LLM triyajı
     (`source=llm:<provider>`, geçerli severity/confidence).

Anahtar yoksa atlanır (CI yeşil kalır). Çalıştırma:
    MIRAGE_LLM_PROVIDER=openai OPENAI_API_KEY=... python3 -m pytest scripts/test_llm_live.py -v
    MIRAGE_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=... python3 -m pytest scripts/test_llm_live.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage.agent import CanaryRegistry, scan_text_for_leaks  # noqa: E402
from mirage.llm import available_providers, get_llm_provider  # noqa: E402
from mirage.llm.provider import LLMMessage  # noqa: E402
from mirage.llm.triage import VALID_ACTIONS, VALID_SEVERITIES  # noqa: E402

pytestmark = pytest.mark.skipif(
    not available_providers(),
    reason="No LLM provider key set (OPENAI_API_KEY / ANTHROPIC_API_KEY)",
)


def _provider():
    provider = get_llm_provider()
    assert provider is not None, "key var ama sağlayıcı kurulmadı"
    return provider


def test_hybrid_explicit_selection():
    """Her iki sağlayıcı da (anahtarı varsa) açıkça seçilebilmeli."""
    providers = available_providers()
    if "openai" in providers:
        assert get_llm_provider("openai").name == "openai"
    if "anthropic" in providers:
        assert get_llm_provider("anthropic").name == "anthropic"


def test_provider_real_completion():
    provider = _provider()
    response = asyncio.run(
        provider.complete(
            [LLMMessage(role="user", content="Reply with exactly: pong")],
            max_tokens=16,
        )
    )
    assert response.text.strip(), "sağlayıcı boş yanıt döndü"
    assert response.provider in available_providers()
    assert response.model


def test_canary_leak_end_to_end_llm_triage():
    provider = _provider()
    registry = CanaryRegistry()
    canary = registry.issue("system_prompt")
    leak = asyncio.run(
        scan_text_for_leaks(
            registry=registry,
            text=f"Unrelated output that leaked: {canary.marker}",
            provider=provider,
        )
    )
    assert leak["leaked"] is True
    assert leak["count"] == 1
    triage = leak["triage"]
    assert triage["source"].startswith("llm:"), triage
    assert triage["severity"] in VALID_SEVERITIES
    assert triage["recommended_action"] in VALID_ACTIONS
    assert 0.0 <= float(triage["confidence"]) <= 1.0


if __name__ == "__main__":
    if not available_providers():
        print("SKIP: no LLM provider key set (OPENAI_API_KEY / ANTHROPIC_API_KEY).")
        sys.exit(0)
    print(f"Live LLM smoke — providers: {available_providers()}")
    sys.exit(pytest.main([__file__, "-v", "-s"]))
