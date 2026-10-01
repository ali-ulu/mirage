"""
PR A — Beacon triyaj kaydı: store + FastAPI endpoint testleri.

Strateji:
  - Store testleri: supabase-py chain API'sini taklit eden mock client ile.
  - Endpoint testleri: TestClient + enjekte edilmiş mock triyaj store'u ile
    (reset_triage_store_for_testing). LLM sağlayıcısı sınırda monkeypatch'lenir.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.llm import LLMProvider, LLMResponse  # noqa: E402
from mirage.llm.triage import TriageResult  # noqa: E402
from mirage.triage_store import BeaconTriageStore  # noqa: E402

TOKEN = "550e8400-e29b-41d4-a716-446655440000"


class _MockChain:
    """supabase-py chain API taklidi: table().insert().execute() / select()..."""

    def __init__(self, storage: dict, table: str):
        self.storage = storage
        self.table_name = table
        self._payload = None
        self._filters: list[tuple[str, object]] = []
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None
        self._select = False

    def insert(self, payload):
        self._payload = payload
        self.storage.setdefault(self.table_name, []).append(dict(payload))
        return self

    def select(self, *_a):
        self._select = True
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        if self._payload is not None:
            return type("R", (), {"data": [self._payload], "error": None})()
        rows = list(self.storage.get(self.table_name, []))
        for col, val in self._filters:
            rows = [r for r in rows if r.get(col) == val]
        if self._order:
            col, desc = self._order
            rows.sort(key=lambda r: str(r.get(col, "")), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return type("R", (), {"data": rows, "error": None})()


class MockSupabaseClient:
    def __init__(self):
        self.storage: dict[str, list] = {}

    def table(self, name):
        return _MockChain(self.storage, name)


# ---------------------------------------------------------------------------
# Store testleri
# ---------------------------------------------------------------------------
def _result(**kw) -> TriageResult:
    base = dict(
        severity="high",
        confidence=0.8,
        rationale="dağıtık yoklama",
        recommended_action="investigate",
        source="heuristic",
        chain_verified=True,
    )
    base.update(kw)
    return TriageResult(**base)


def test_store_save_and_list_roundtrip():
    client = MockSupabaseClient()
    store = BeaconTriageStore(client=client)
    store.save(TOKEN, _result(), chain_seq=3, model=None)

    rows = store.list_for_token(TOKEN)
    assert len(rows) == 1
    assert rows[0].token == TOKEN
    assert rows[0].severity == "high"
    assert rows[0].recommended_action == "investigate"
    assert rows[0].chain_seq == 3
    assert rows[0].chain_verified is True


def test_store_rejects_invalid_severity():
    store = BeaconTriageStore(client=MockSupabaseClient())
    try:
        store.save(TOKEN, _result(severity="banana"))
        raise AssertionError("invalid severity kabul edilmemeli")
    except ValueError:
        pass


def test_store_rejects_out_of_range_confidence():
    store = BeaconTriageStore(client=MockSupabaseClient())
    try:
        store.save(TOKEN, _result(confidence=2.0))
        raise AssertionError("confidence > 1 kabul edilmemeli")
    except ValueError:
        pass


def test_store_list_returns_empty_on_error():
    class Boom:
        def table(self, _n):
            raise RuntimeError("db down")

    store = BeaconTriageStore(client=Boom())
    assert store.list_for_token(TOKEN) == []


# ---------------------------------------------------------------------------
# Endpoint testleri
# ---------------------------------------------------------------------------
def _client_with_mock_store():
    mock = MockSupabaseClient()
    server.reset_triage_store_for_testing(mock)
    return TestClient(server.app), mock


def test_triage_endpoint_heuristic_persists(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client, mock = _client_with_mock_store()
    res = client.post(
        "/beacon/triage",
        json={"token": TOKEN, "event": {"distinct_ips": 3, "user_agent": "curl"}},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["source"] == "heuristic"
    assert body["severity"] == "high"
    assert body["persisted"] is True
    assert len(mock.storage.get("beacon_triage", [])) == 1


def test_triage_endpoint_without_persist_writes_nothing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client, mock = _client_with_mock_store()
    res = client.post(
        "/beacon/triage",
        json={"token": TOKEN, "event": {"user_agent": "Mozilla/5.0"}, "persist": False},
    )
    assert res.status_code == 201
    assert res.json()["persisted"] is False
    assert mock.storage.get("beacon_triage", []) == []


def test_triage_endpoint_list_roundtrip(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client, _ = _client_with_mock_store()
    client.post("/beacon/triage", json={"token": TOKEN, "event": {"distinct_ips": 3}})
    res = client.get(f"/beacon/triage/{TOKEN}")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["records"][0]["token"] == TOKEN


def test_triage_endpoint_llm_path_records_model(monkeypatch):
    class _Fake(LLMProvider):
        name = "openai"
        _model = "gpt-4o-mini"

        async def complete(self, messages, *, max_tokens=512, temperature=0.0, json_mode=False):
            return LLMResponse(
                text='{"severity":"critical","confidence":0.9,"rationale":"APT","recommended_action":"escalate"}',
                provider=self.name,
                model=self._model,
            )

    monkeypatch.setattr(server, "get_llm_provider", lambda *a, **k: _Fake())
    client, mock = _client_with_mock_store()
    res = client.post("/beacon/triage", json={"token": TOKEN, "event": {"token": TOKEN}})
    assert res.status_code == 201
    body = res.json()
    assert body["source"] == "llm:openai"
    assert body["model"] == "gpt-4o-mini"
    assert mock.storage["beacon_triage"][0]["model"] == "gpt-4o-mini"


def test_triage_endpoint_fails_closed_without_store(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    server.reset_triage_store_for_testing(None)
    # Supabase env yoksa store oluşturulamaz -> 503
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    client = TestClient(server.app)
    res = client.post("/beacon/triage", json={"token": TOKEN, "event": {}})
    assert res.status_code == 503


def test_triage_endpoint_requires_api_token_in_production(monkeypatch):
    monkeypatch.setenv("MIRAGE_ENV", "production")
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    client = TestClient(server.app)
    res = client.post("/beacon/triage", json={"token": TOKEN, "event": {}})
    assert res.status_code == 503
