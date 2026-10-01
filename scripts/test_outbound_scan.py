"""
PR — Giden (upstream) tarama + otomatik triyaj sink testleri.

Kapsam:
  - `OutboundScanner`: temiz/ihlal raporu, blok modu (fail-closed), tarama hatası.
  - `POST /agent/scan` `block` modu: ihlalde 422, temizde 200.
  - `build_triage_sink`: sızıntıyı senkron heuristic ile triyaj defterine yazar.
  - `install_agent_scan_middleware(persist=True)`: triage_sink bağlanır.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.agent import CanaryRegistry, OutboundLeakError, OutboundScanner  # noqa: E402
from mirage.agent.middleware import build_triage_sink, scan_persist_enabled  # noqa: E402


class _MockChain:
    def __init__(self, storage, table):
        self.storage = storage
        self.table_name = table
        self._payload = None

    def insert(self, payload):
        self._payload = payload
        self.storage.setdefault(self.table_name, []).append(dict(payload))
        return self

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        if self._payload is not None:
            return type("R", (), {"data": [self._payload], "error": None})()
        return type("R", (), {"data": list(self.storage.get(self.table_name, [])), "error": None})()


class MockSupabaseClient:
    def __init__(self):
        self.storage = {}

    def table(self, name):
        return _MockChain(self.storage, name)


# ---------------------------------------------------------------------------
# OutboundScanner
# ---------------------------------------------------------------------------
def test_outbound_clean():
    scanner = OutboundScanner(rules=[{"name": "aws", "pattern": r"sk-[A-Z0-9]+"}])
    report = scanner.scan("merhaba dünya")
    assert report["clean"] is True
    assert report["rule_hits"] == 0


def test_outbound_canary_hit():
    reg = CanaryRegistry()
    canary = reg.issue("system_prompt")
    scanner = OutboundScanner(registry=reg)
    report = scanner.scan(f"payload {canary.marker}")
    assert report["leaked"] is True
    assert report["count"] == 1
    assert report["clean"] is False


def test_outbound_rule_hit():
    scanner = OutboundScanner(rules=[{"name": "aws", "pattern": r"sk-[A-Z0-9]+"}])
    report = scanner.scan("key sk-ABC123")
    assert report["rule_hits"] == 1
    assert report["clean"] is False


def test_outbound_block_raises_on_leak():
    scanner = OutboundScanner(rules=[{"name": "aws", "pattern": r"sk-[A-Z0-9]+"}], block=True)
    try:
        scanner.guard("sk-SECRET")
        raise AssertionError("blok modunda ihlal yükseltmeli")
    except OutboundLeakError as e:
        assert e.leak["rule_hits"] == 1


def test_outbound_block_passes_clean():
    scanner = OutboundScanner(rules=[{"name": "aws", "pattern": r"sk-[A-Z0-9]+"}], block=True)
    assert scanner.guard("temiz")["clean"] is True


def test_outbound_scan_error_fail_closed():
    class Boom:
        def match(self, _t):
            raise RuntimeError("registry down")

    scanner = OutboundScanner(registry=Boom(), block=True)
    try:
        scanner.guard("anything")
        raise AssertionError("tarama hatası blok modunda fail-closed olmalı")
    except OutboundLeakError as e:
        assert e.leak.get("reason") == "scan_error"


# ---------------------------------------------------------------------------
# /agent/scan block modu
# ---------------------------------------------------------------------------
def _client():
    return TestClient(server.app)


def test_endpoint_block_returns_422_on_rule_hit(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    r = _client().post(
        "/agent/scan",
        json={"text": "key sk-XYZ", "block": True, "rules": [{"name": "aws", "pattern": r"sk-[A-Z0-9]+"}]},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["rule_hits"] == 1


def test_endpoint_block_returns_200_when_clean(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    r = _client().post("/agent/scan", json={"text": "temiz çıktı", "block": True})
    assert r.status_code == 200
    assert r.json()["clean"] is True


def test_endpoint_without_block_returns_200_on_leak(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    r = _client().post(
        "/agent/scan",
        json={"text": "sk-XYZ", "rules": [{"name": "aws", "pattern": r"sk-[A-Z0-9]+"}]},
    )
    assert r.status_code == 200
    assert r.json()["clean"] is False


# ---------------------------------------------------------------------------
# Otomatik triyaj sink
# ---------------------------------------------------------------------------
def test_scan_persist_enabled_env(monkeypatch):
    monkeypatch.delenv("MIRAGE_SCAN_PERSIST", raising=False)
    assert scan_persist_enabled() is False
    monkeypatch.setenv("MIRAGE_SCAN_PERSIST", "on")
    assert scan_persist_enabled() is True


def test_build_triage_sink_persists():
    client = MockSupabaseClient()
    server.reset_triage_store_for_testing(client=client)
    sink = build_triage_sink()
    leak = {
        "count": 1,
        "canaries": [{"token": "550e8400-e29b-41d4-a716-446655440000", "team_id": None}],
        "findings": [],
    }
    sink("text", leak)
    rows = client.storage.get("beacon_triage", [])
    assert len(rows) == 1
    assert rows[0]["token"] == "550e8400-e29b-41d4-a716-446655440000"
    assert rows[0]["source"] == "heuristic"
    server.reset_triage_store_for_testing()


def test_build_triage_sink_skips_without_token():
    client = MockSupabaseClient()
    server.reset_triage_store_for_testing(client=client)
    build_triage_sink()("text", {"count": 1, "canaries": [{"marker": "x"}], "findings": []})
    assert client.storage.get("beacon_triage", []) == []
    server.reset_triage_store_for_testing()


def test_install_binds_sink_when_persist(monkeypatch):
    monkeypatch.setenv("MIRAGE_SCAN_MIDDLEWARE", "true")
    monkeypatch.delenv("MIRAGE_SCAN_PERSIST", raising=False)
    server.reset_canary_registry_for_testing()
    server.reset_triage_store_for_testing(client=MockSupabaseClient())

    from fastapi import FastAPI
    from mirage.agent import AgentScanMiddleware

    app = FastAPI()
    server.install_agent_scan_middleware(app, persist=True)
    entry = next(m for m in app.user_middleware if m.cls is AgentScanMiddleware)
    assert entry.kwargs.get("triage_sink") is not None
    server.reset_triage_store_for_testing()
