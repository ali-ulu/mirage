"""
MIRAGE — Gerçek LLM sağlayıcı smoke testi (opt-in).

Bu test, yapılandırılmış bir sağlayıcı anahtarı (OPENAI_API_KEY veya
ANTHROPIC_API_KEY) varsa **gerçek** API çağrısı yapar ve LLM yolunun uçtan uca
çalıştığını doğrular. Anahtar yoksa **atlanır** (skip) — CI'da yeşil kalır,
yerelde `MIRAGE_LLM_PROVIDER` + anahtar verildiğinde gerçek smoke koşar.

Çalıştırma (örnek):
    MIRAGE_LLM_PROVIDER=openai OPENAI_API_KEY=... python scripts/test_llm_smoke.py
    MIRAGE_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=... pytest scripts/test_llm_smoke.py

Not: Ağ erişimi gerekir. Anahtar yoksa hiçbir istek yapılmaz.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage.agent.canary_triage import triage_canary  # noqa: E402
from mirage.llm import available_providers, get_llm_provider, triage_beacon  # noqa: E402

pytestmark = pytest.mark.skipif(
    not available_providers(),
    reason="No LLM provider key set (OPENAI_API_KEY / ANTHROPIC_API_KEY)",
)

_BEACON_EVENT = {
    "distinct_ips": 3,
    "total_hits": 5,
    "user_agents": ["Microsoft Excel/16.0", "python-requests/2.31"],
}

_CANARY_LEAK = {
    "count": 2,
    "contexts": ["system_prompt", "rag_document"],
    "canaries": [
        {"marker": "[[MIRAGE-CANARY:aaaa]]", "context": "system_prompt"},
        {"marker": "[[MIRAGE-CANARY:bbbb]]", "context": "rag_document"},
    ],
}


def test_beacon_triage_real_llm():
    provider = get_llm_provider()
    assert provider is not None, "provider expected when a key is set"
    result = asyncio.run(triage_beacon(_BEACON_EVENT, provider=provider, chain_ok=False))
    assert result.source.startswith("llm:"), result
    assert result.severity in ("low", "medium", "high", "critical")
    assert 0.0 <= result.confidence <= 1.0


def test_canary_triage_real_llm():
    provider = get_llm_provider()
    assert provider is not None, "provider expected when a key is set"
    result = asyncio.run(triage_canary(_CANARY_LEAK, provider=provider, chain_ok=True))
    assert result.source.startswith("llm:"), result
    assert result.recommended_action in ("ignore", "monitor", "investigate", "escalate")


if __name__ == "__main__":
    providers = available_providers()
    if not providers:
        print("SKIP: no LLM provider key set (OPENAI_API_KEY / ANTHROPIC_API_KEY).")
        sys.exit(0)
    print(f"Running real LLM smoke with providers: {providers}")
    sys.exit(pytest.main([__file__, "-v", "-s"]))
