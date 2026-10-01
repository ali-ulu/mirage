"""
MIRAGE — Canary sızıntısı triyajı testleri.

Çekirdek LLM'siz deterministik; LLM yolu ve dayanıklılık, sahte (test double)
sağlayıcılarla doğrulanır. Uçlar, gerçek kod yollarını çalıştırır (mock yok);
yalnızca Supabase client testte taklit edilir.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.agent import build_canary_triage_messages, triage_canary  # noqa: E402
from mirage.llm.provider import LLMError, LLMProvider, LLMResponse  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Test double'lar
# ---------------------------------------------------------------------------
class _FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, text: str):
        self._text = text

    async def complete(self, messages, *, max_tokens=512, temperature=0.0, json_mode=False):
        return LLMResponse(text=self._text, provider=self.name, model="fake-1")


class _ExplodingProvider(LLMProvider):
    name = "boom"

    async def complete(self, messages, *, max_tokens=512, temperature=0.0, json_mode=False):
        raise LLMError("provider down")


class _FakeChain:
    def __init__(self, storage):
        self.storage = storage
        self._payload = None
        self._filters = []

    def insert(self, payload):
        self._payload = payload
        self.storage.setdefault("beacon_triage", []).append(payload)
        return self

    def select(self, *_a):
        return self

    def eq(self, col, value):
        self._filters.append((col, value))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        rows = list(self.storage.get("beacon_triage", []))
        for col, value in self._filters:
            rows = [r for r in rows if str(r.get(col)) == str(value)]
        return type("R", (), {"data": rows})()


class _FakeClient:
    def __init__(self):
        self.storage: dict = {}

    def table(self, name):
        return _FakeChain(self.storage)


# ---------------------------------------------------------------------------
# Heuristic
# ---------------------------------------------------------------------------
def test_heuristic_single_rag_leak_is_low():
    result = _run(triage_canary({"count": 1, "contexts": ["rag_document"]}))
    assert result.source == "heuristic"
    assert result.severity == "low"
    assert result.recommended_action == "ignore"


def test_heuristic_single_system_prompt_leak_is_medium():
    result = _run(triage_canary({"count": 1, "contexts": ["system_prompt"]}))
    assert result.severity == "medium"
    assert result.recommended_action == "monitor"


def test_heuristic_multi_context_leak_is_high():
    result = _run(triage_canary({"count": 2, "contexts": ["system_prompt", "rag_document"]}))
    assert result.severity == "high"
    assert result.recommended_action == "investigate"


def test_heuristic_chain_broken_is_critical():
    result = _run(
        triage_canary({"count": 1, "contexts": ["rag_document"]}, chain_ok=False)
    )
    assert result.severity == "critical"
    assert result.recommended_action == "escalate"


def test_heuristic_records_chain_verified():
    result = _run(triage_canary({"count": 1, "contexts": ["rag_document"]}, chain_ok=True))
    assert result.chain_verified is True


# ---------------------------------------------------------------------------
# LLM yolu ve dayanıklılık
# ---------------------------------------------------------------------------
def test_llm_result_is_used():
    provider = _FakeProvider(
        '{"severity": "critical", "confidence": 0.9, "rationale": "sızıntı", '
        '"recommended_action": "escalate"}'
    )
    result = _run(triage_canary({"count": 1, "contexts": ["system_prompt"]}, provider=provider))
    assert result.source == "llm:fake"
    assert result.severity == "critical"
    assert result.confidence == 0.9


def test_llm_invalid_schema_falls_back_to_heuristic():
    provider = _FakeProvider('{"severity": "banana", "recommended_action": "nope"}')
    result = _run(
        triage_canary({"count": 2, "contexts": ["system_prompt", "rag_document"]}, provider=provider)
    )
    assert result.source == "heuristic"
    assert result.severity == "high"


def test_llm_error_falls_back_to_heuristic():
    result = _run(
        triage_canary({"count": 1, "contexts": ["system_prompt"]}, provider=_ExplodingProvider())
    )
    assert result.source == "heuristic"
    assert "LLM kullanılamadı" in result.rationale


def test_build_messages_contains_leak_and_chain():
    messages = build_canary_triage_messages({"count": 1, "contexts": ["rag_document"]}, True)
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert "rag_document" in messages[1].content
    assert "chain_verified" in messages[1].content


# ---------------------------------------------------------------------------
# HTTP — /agent/canary/check
# ---------------------------------------------------------------------------
def test_check_returns_triage_on_leak(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    api = TestClient(server.app)
    issued = api.post("/agent/canary", json={"context": "system_prompt"}).json()

    res = api.post("/agent/canary/check", json={"text": f"cevap: {issued['marker']}"})
    body = res.json()
    assert body["leaked"] is True
    assert "triage" in body
    assert body["triage"]["source"] == "heuristic"
    assert body["persisted"] is False


def test_check_no_leak_has_no_triage(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    api = TestClient(server.app)
    api.post("/agent/canary", json={"context": "rag_document"})
    body = api.post("/agent/canary/check", json={"text": "temiz"}).json()
    assert body["leaked"] is False
    assert "triage" not in body


def test_check_persists_leak_to_triage_ledger(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    fake = _FakeClient()
    server.reset_triage_store_for_testing(client=fake)
    try:
        api = TestClient(server.app)
        issued = api.post("/agent/canary", json={"context": "system_prompt"}).json()
        token = "11111111-2222-3333-4444-555555555555"
        body = api.post(
            "/agent/canary/check",
            json={
                "text": f"cevap: {issued['marker']}",
                "token": token,
                "persist": True,
            },
        ).json()
        assert body["persisted"] is True
        rows = fake.storage["beacon_triage"]
        assert len(rows) == 1
        assert rows[0]["token"] == token
        assert rows[0]["severity"] in ("low", "medium", "high", "critical")
    finally:
        server.reset_triage_store_for_testing()
