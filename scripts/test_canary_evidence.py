"""
MIRAGE — Canary sızıntısının kanıt zincirine bağlanması testleri.

`resolve_chain_binding` saf fonksiyondur; sahte (test double) evidence store ile
doğrulanır. Uç testleri gerçek kod yollarını çalıştırır; yalnızca kanıt store'u
testte monkeypatch ile değiştirilir (production kod mock içermez).
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.agent import resolve_chain_binding  # noqa: E402
from mirage.supabase_registry import SupabaseOperationError  # noqa: E402


class _FakeEvidenceStore:
    def __init__(self, records=None, verify_result=None, raises=False):
        self._records = records or []
        self._verify = verify_result or {"ok": True, "reason": None}
        self._raises = raises

    def list_chain(self, token):
        if self._raises:
            raise SupabaseOperationError("boom")
        return list(self._records)

    def verify(self, token):
        if self._raises:
            raise SupabaseOperationError("boom")
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
# resolve_chain_binding (saf fonksiyon)
# ---------------------------------------------------------------------------
def test_no_token_is_not_linked():
    b = resolve_chain_binding(_FakeEvidenceStore(), None)
    assert b["linked"] is False
    assert b["chain_seq"] is None
    assert b["reason"] == "no token provided"


def test_store_unavailable_is_not_linked():
    b = resolve_chain_binding(None, "11111111-1111-1111-1111-111111111111")
    assert b["linked"] is False
    assert b["reason"] == "evidence store unavailable"


def test_no_records_is_not_linked():
    b = resolve_chain_binding(_FakeEvidenceStore(records=[]), "11111111-1111-1111-1111-111111111111")
    assert b["linked"] is False
    assert b["reason"] == "no evidence records for token"


def test_records_bind_head_and_verified():
    records = [
        {"chain_seq": 1, "record_hash": "a"},
        {"chain_seq": 3, "record_hash": "c"},
        {"chain_seq": 2, "record_hash": "b"},
    ]
    store = _FakeEvidenceStore(records=records, verify_result={"ok": True, "reason": None})
    b = resolve_chain_binding(store, "11111111-1111-1111-1111-111111111111")
    assert b["linked"] is True
    assert b["chain_seq"] == 3  # zincir başı = en yüksek sıra
    assert b["chain_verified"] is True


def test_records_bind_and_report_broken_chain():
    records = [{"chain_seq": 1, "record_hash": "a"}]
    store = _FakeEvidenceStore(records=records, verify_result={"ok": False, "reason": "hmac verification failed"})
    b = resolve_chain_binding(store, "11111111-1111-1111-1111-111111111111")
    assert b["linked"] is True
    assert b["chain_verified"] is False
    assert b["reason"] == "hmac verification failed"


def test_store_error_is_fail_safe():
    b = resolve_chain_binding(_FakeEvidenceStore(raises=True), "11111111-1111-1111-1111-111111111111")
    assert b["linked"] is False
    assert b["reason"] == "evidence store unavailable"


# ---------------------------------------------------------------------------
# HTTP — /agent/canary/check kanıt bağı
# ---------------------------------------------------------------------------
def _issue(api):
    return api.post("/agent/canary", json={"context": "system_prompt"}).json()


def test_check_links_leak_to_evidence_chain(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    records = [{"chain_seq": 5, "record_hash": "h"}]
    monkeypatch.setattr(
        server, "get_evidence_store",
        lambda: _FakeEvidenceStore(records=records, verify_result={"ok": True, "reason": None}),
    )
    api = TestClient(server.app)
    issued = _issue(api)
    token = "11111111-1111-1111-1111-111111111111"
    body = api.post(
        "/agent/canary/check",
        json={"text": f"cevap: {issued['marker']}", "token": token},
    ).json()
    assert body["chain_linked"] is True
    assert body["chain_seq"] == 5
    assert body["triage"]["chain_verified"] is True


def test_check_persists_with_chain_seq(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    records = [{"chain_seq": 7, "record_hash": "h"}]
    monkeypatch.setattr(
        server, "get_evidence_store",
        lambda: _FakeEvidenceStore(records=records, verify_result={"ok": True, "reason": None}),
    )
    fake_client = _FakeClient()
    server.reset_triage_store_for_testing(client=fake_client)
    try:
        api = TestClient(server.app)
        issued = _issue(api)
        token = "11111111-1111-1111-1111-111111111111"
        body = api.post(
            "/agent/canary/check",
            json={"text": f"cevap: {issued['marker']}", "token": token, "persist": True},
        ).json()
        assert body["persisted"] is True
        assert fake_client.storage["beacon_triage"][0]["chain_seq"] == 7
    finally:
        server.reset_triage_store_for_testing()


def test_check_unlinked_when_no_evidence(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    monkeypatch.setattr(server, "get_evidence_store", lambda: _FakeEvidenceStore(records=[]))
    api = TestClient(server.app)
    issued = _issue(api)
    body = api.post(
        "/agent/canary/check",
        json={"text": f"cevap: {issued['marker']}", "token": "11111111-1111-1111-1111-111111111111"},
    ).json()
    assert body["chain_linked"] is False
    assert body["chain_seq"] is None


def test_check_without_token_stays_unlinked(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing()
    api = TestClient(server.app)
    issued = _issue(api)
    body = api.post("/agent/canary/check", json={"text": f"cevap: {issued['marker']}"}).json()
    assert body["chain_linked"] is False
    assert body["triage"]["chain_verified"] is None
