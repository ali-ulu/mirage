"""
MIRAGE — Runtime tarama katmanı testleri (`/agent/scan`, `evaluate_rules`).

`scan_text_for_leaks` gerçek kod yoludur; yalnızca evidence/triage store'ları
test double ile değiştirilir. Kural motoru saf fonksiyondur.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.agent import CanaryRegistry, evaluate_rules, scan_text_for_leaks  # noqa: E402
from mirage.supabase_registry import SupabaseNotConfiguredError, SupabaseOperationError  # noqa: E402


class _FakeEvidenceStore:
    def __init__(self, records=None, verify_result=None):
        self._records = records or []
        self._verify = verify_result or {"ok": True, "reason": None}

    def list_chain(self, token):
        return list(self._records)

    def verify(self, token):
        return self._verify


class _FakeChain:
    def __init__(self, storage):
        self.storage = storage

    def insert(self, payload):
        self.storage.setdefault("beacon_triage", []).append(payload)
        return self

    def execute(self):
        return type("R", (), {"data": []})()


class _FakeClient:
    def __init__(self):
        self.storage: dict = {}

    def table(self, name):
        return _FakeChain(self.storage)


# ---------------------------------------------------------------------------
# evaluate_rules (saf)
# ---------------------------------------------------------------------------
def test_rules_match():
    findings = evaluate_rules(
        "key=AKIA1234567890 and secret",
        [
            {"name": "aws_key", "pattern": r"AKIA[0-9]{10}", "severity": "high"},
            {"name": "absent", "pattern": r"ZZZZ", "severity": "low"},
        ],
    )
    assert len(findings) == 1
    assert findings[0]["name"] == "aws_key"
    assert findings[0]["severity"] == "high"


def test_invalid_regex_is_fail_safe():
    findings = evaluate_rules("x", [{"name": "bad", "pattern": "([", "severity": "low"}])
    assert findings[0]["error"] == "invalid regex"


# ---------------------------------------------------------------------------
# scan_text_for_leaks (orkestrasyon)
# ---------------------------------------------------------------------------
def test_scan_clean_returns_not_leaked():
    registry = CanaryRegistry()
    out = asyncio.run(scan_text_for_leaks(registry=registry, text="temiz çıktı"))
    assert out["leaked"] is False
    assert out["count"] == 0


def test_scan_detects_canary_and_triages():
    registry = CanaryRegistry()
    canary = registry.issue(context="system_prompt")
    out = asyncio.run(
        scan_text_for_leaks(registry=registry, text=f"cevap: {canary.marker}")
    )
    assert out["leaked"] is True
    assert out["triage"]["source"] == "heuristic"
    assert out["triage"]["severity"] in ("low", "medium", "high", "critical")


def test_scan_persist_without_ledger_raises():
    registry = CanaryRegistry()
    canary = registry.issue(context="agent_memory")
    try:
        asyncio.run(
            scan_text_for_leaks(
                registry=registry,
                text=canary.marker,
                token="11111111-1111-1111-1111-111111111111",
                persist=True,
                triage_store=None,
            )
        )
        assert False, "expected SupabaseNotConfiguredError"
    except SupabaseNotConfiguredError:
        pass


# ---------------------------------------------------------------------------
# HTTP — /agent/scan
# ---------------------------------------------------------------------------
def _issue(api, context="system_prompt"):
    return api.post("/agent/canary", json={"context": context}).json()


def test_scan_endpoint_clean(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    api = TestClient(server.app)
    body = api.post("/agent/scan", json={"text": "normal ajan çıktısı"}).json()
    assert body["clean"] is True
    assert body["leaked"] is False
    assert body["rule_hits"] == 0


def test_scan_endpoint_canary_leak(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    monkeypatch.setattr(server, "get_evidence_store", lambda: _FakeEvidenceStore(records=[]))
    api = TestClient(server.app)
    issued = _issue(api)
    body = api.post(
        "/agent/scan",
        json={"text": f"log: {issued['marker']}", "source": "agent-output"},
    ).json()
    assert body["clean"] is False
    assert body["leaked"] is True
    assert body["source"] == "agent-output"
    assert "triage" in body


def test_scan_endpoint_rule_hit(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    api = TestClient(server.app)
    body = api.post(
        "/agent/scan",
        json={
            "text": "token=AKIA1234567890",
            "rules": [{"name": "aws_key", "pattern": r"AKIA[0-9]{10}", "severity": "high"}],
        },
    ).json()
    assert body["rule_hits"] == 1
    assert body["rules"][0]["name"] == "aws_key"
    assert body["clean"] is False


def test_scan_endpoint_persists_with_chain_seq(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    monkeypatch.setattr(
        server, "get_evidence_store",
        lambda: _FakeEvidenceStore(records=[{"chain_seq": 9, "record_hash": "h"}]),
    )
    fake_client = _FakeClient()
    server.reset_triage_store_for_testing(client=fake_client)
    try:
        api = TestClient(server.app)
        issued = _issue(api)
        body = api.post(
            "/agent/scan",
            json={
                "text": f"log: {issued['marker']}",
                "token": "11111111-1111-1111-1111-111111111111",
                "persist": True,
            },
        ).json()
        assert body["persisted"] is True
        assert body["chain_seq"] == 9
        assert fake_client.storage["beacon_triage"][0]["chain_seq"] == 9
    finally:
        server.reset_triage_store_for_testing()
