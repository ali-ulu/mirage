"""
MIRAGE — Multi-tenant team_id testleri.

Kapsam: prompt canary (in-memory + Supabase store), beacon triyaj store ve
HTTP uçları. Supabase client test double ile taklit edilir; production kod
mock içermez.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.agent import CanaryRegistry  # noqa: E402
from mirage.canary_store import SupabaseCanaryRegistry  # noqa: E402
from mirage.llm.triage import TriageResult  # noqa: E402
from mirage.triage_store import BeaconTriageStore  # noqa: E402

TEAM_A = "aaaaaaaa-0000-0000-0000-000000000001"
TEAM_B = "bbbbbbbb-0000-0000-0000-000000000002"
TOKEN = "550e8400-e29b-41d4-a716-446655440000"


class _Chain:
    def __init__(self, storage, table):
        self.storage = storage
        self.table_name = table
        self._payload = None
        self._filters = []
        self._order = None
        self._limit = None
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
            rows = [r for r in rows if str(r.get(col)) == str(val)]
        if self._order:
            col, desc = self._order
            rows.sort(key=lambda r: str(r.get(col) or ""), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return type("R", (), {"data": rows, "error": None})()


class _Client:
    def __init__(self):
        self.storage = {}

    def table(self, name):
        return _Chain(self.storage, name)


# ---------------------------------------------------------------------------
# In-memory registry
# ---------------------------------------------------------------------------
def test_registry_issue_records_team_id():
    reg = CanaryRegistry()
    canary = reg.issue("system_prompt", label="x", team_id=TEAM_A)
    assert canary.team_id == TEAM_A
    assert canary.to_dict()["team_id"] == TEAM_A


def test_registry_team_id_defaults_none():
    reg = CanaryRegistry()
    assert reg.issue("rag_document").team_id is None


# ---------------------------------------------------------------------------
# Supabase canary store
# ---------------------------------------------------------------------------
def test_canary_store_persists_team_id():
    client = _Client()
    reg = SupabaseCanaryRegistry(client=client)
    reg.issue("agent_memory", label="m", team_id=TEAM_A)
    assert client.storage["prompt_canaries"][0]["team_id"] == TEAM_A


def test_canary_store_all_records_filters_by_team():
    client = _Client()
    reg = SupabaseCanaryRegistry(client=client)
    reg.issue("system_prompt", team_id=TEAM_A)
    reg.issue("system_prompt", team_id=TEAM_B)
    only_a = reg.all_records(team_id=TEAM_A)
    assert len(only_a) == 1
    assert only_a[0].team_id == TEAM_A
    assert len(reg.all_records()) == 2


# ---------------------------------------------------------------------------
# Triage store
# ---------------------------------------------------------------------------
def _result() -> TriageResult:
    return TriageResult(
        severity="high", confidence=0.8, rationale="r",
        recommended_action="investigate", source="heuristic", chain_verified=True,
    )


def test_triage_store_persists_team_id():
    client = _Client()
    store = BeaconTriageStore(client=client)
    rec = store.save(TOKEN, _result(), team_id=TEAM_A)
    assert rec.team_id == TEAM_A
    assert client.storage["beacon_triage"][0]["team_id"] == TEAM_A


def test_triage_store_list_filters_by_team():
    client = _Client()
    store = BeaconTriageStore(client=client)
    store.save(TOKEN, _result(), team_id=TEAM_A)
    store.save(TOKEN, _result(), team_id=TEAM_B)
    assert len(store.list_for_token(TOKEN, team_id=TEAM_A)) == 1
    assert len(store.list_for_token(TOKEN)) == 2


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def test_issue_canary_endpoint_records_team(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    client = TestClient(server.app)
    body = client.post(
        "/agent/canary", json={"context": "system_prompt", "team_id": TEAM_A}
    ).json()
    assert body["team_id"] == TEAM_A


def test_scan_endpoint_accepts_team(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    client = TestClient(server.app)
    issued = client.post(
        "/agent/canary", json={"context": "system_prompt", "team_id": TEAM_A}
    ).json()
    body = client.post(
        "/agent/scan",
        json={"text": f"log: {issued['marker']}", "team_id": TEAM_A},
    ).json()
    assert body["leaked"] is True
