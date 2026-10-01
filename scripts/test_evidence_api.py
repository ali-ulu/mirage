"""
PR B — Kanıt doğrulama API'si: store + endpoint testleri.

Strateji:
  - Store: mock Supabase client ile gerçek `verify_chain` kod yolu çalıştırılır.
  - Endpoint: TestClient + enjekte edilmiş mock store.
  - DB timestamptz gidiş-dönüşü (`+00:00`) doğrulamayı bozmamalı.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.evidence import GENESIS_HASH, build_evidence_record  # noqa: E402
from mirage.evidence_store import EvidenceChainStore  # noqa: E402

TOKEN = "550e8400-e29b-41d4-a716-446655440000"
KEY = "test-key-0123456789abcdef"


class _MockChain:
    def __init__(self, storage: dict, table: str):
        self.storage = storage
        self.table_name = table
        self._filters: list[tuple[str, object]] = []
        self._order: tuple[str, bool] | None = None
        self._select = False

    def select(self, *_a):
        self._select = True
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def execute(self):
        rows = list(self.storage.get(self.table_name, []))
        for col, val in self._filters:
            rows = [r for r in rows if r.get(col) == val]
        if self._order:
            col, desc = self._order
            rows.sort(key=lambda r: r.get(col, 0), reverse=desc)
        return type("R", (), {"data": rows, "error": None})()


class MockSupabaseClient:
    def __init__(self, rows=None):
        self.storage = {"triggered_beacons": list(rows or [])}

    def table(self, name):
        return _MockChain(self.storage, name)


def _chain(n: int, *, db_form=False):
    """n kayıtlı, gerçek hash/HMAC'li bir kanıt zinciri üretir."""
    records = []
    prev = GENESIS_HASH
    for seq in range(1, n + 1):
        rec = build_evidence_record(
            key=KEY,
            token=TOKEN,
            ip="203.0.113.42",
            user_agent="LibreOffice/7.5",
            received_at=f"2026-10-01T12:{seq:02d}:00.000Z",
            chain_seq=seq,
            prev_hash=prev,
        )
        if db_form:
            # Postgres timestamptz'ten okunmuş gibi: ...+00:00
            rec["received_at"] = f"2026-10-01T12:{seq:02d}:00+00:00"
        records.append(rec)
        prev = rec["record_hash"]
    return records


# ---------------------------------------------------------------------------
# Store testleri
# ---------------------------------------------------------------------------
def test_store_verify_intact_chain_ok(monkeypatch):
    monkeypatch.setenv("MIRAGE_EVIDENCE_HMAC_KEY", KEY)
    store = EvidenceChainStore(client=MockSupabaseClient(_chain(3)))
    result = store.verify(TOKEN)
    assert result["ok"] is True
    assert result["checked"] == 3
    assert result["token"] == TOKEN


def test_store_verify_survives_db_timestamp_form(monkeypatch):
    """DB'den `+00:00` biçiminde okunan kayıtlar da doğrulanmalı."""
    monkeypatch.setenv("MIRAGE_EVIDENCE_HMAC_KEY", KEY)
    store = EvidenceChainStore(client=MockSupabaseClient(_chain(3, db_form=True)))
    assert store.verify(TOKEN)["ok"] is True


def test_store_verify_detects_tampering(monkeypatch):
    monkeypatch.setenv("MIRAGE_EVIDENCE_HMAC_KEY", KEY)
    records = _chain(3)
    records[1]["ip"] = "10.0.0.1"  # kurcalama
    store = EvidenceChainStore(client=MockSupabaseClient(records))
    result = store.verify(TOKEN)
    assert result["ok"] is False
    assert result["broken_at"] == 2


def test_store_verify_fails_closed_without_key(monkeypatch):
    monkeypatch.delenv("MIRAGE_EVIDENCE_HMAC_KEY", raising=False)
    monkeypatch.delenv("MIRAGE_EDGE_DRY_RUN", raising=False)
    monkeypatch.setenv("MIRAGE_ENV", "production")
    store = EvidenceChainStore(client=MockSupabaseClient(_chain(1)))
    result = store.verify(TOKEN)
    assert result["ok"] is False
    assert result["reason"] == "signing key unavailable"


def test_store_verify_empty_chain_is_ok(monkeypatch):
    monkeypatch.setenv("MIRAGE_EVIDENCE_HMAC_KEY", KEY)
    store = EvidenceChainStore(client=MockSupabaseClient([]))
    result = store.verify(TOKEN)
    assert result["ok"] is True
    assert result["checked"] == 0


# ---------------------------------------------------------------------------
# Endpoint testleri
# ---------------------------------------------------------------------------
def test_list_endpoint_returns_chain(monkeypatch):
    monkeypatch.setenv("MIRAGE_EVIDENCE_HMAC_KEY", KEY)
    server.reset_evidence_store_for_testing(MockSupabaseClient(_chain(2)))
    client = TestClient(server.app)
    res = client.get(f"/beacon/evidence/{TOKEN}")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 2
    assert body["records"][0]["chain_seq"] == 1


def test_verify_endpoint_ok(monkeypatch):
    monkeypatch.setenv("MIRAGE_EVIDENCE_HMAC_KEY", KEY)
    server.reset_evidence_store_for_testing(MockSupabaseClient(_chain(3)))
    client = TestClient(server.app)
    res = client.get(f"/beacon/evidence/{TOKEN}/verify")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_verify_endpoint_reports_broken_chain(monkeypatch):
    monkeypatch.setenv("MIRAGE_EVIDENCE_HMAC_KEY", KEY)
    records = _chain(2)
    records[0]["record_hash"] = "f" * 64
    server.reset_evidence_store_for_testing(MockSupabaseClient(records))
    client = TestClient(server.app)
    res = client.get(f"/beacon/evidence/{TOKEN}/verify")
    assert res.status_code == 200
    assert res.json()["ok"] is False


def test_evidence_endpoints_fail_closed_without_store(monkeypatch):
    server.reset_evidence_store_for_testing(None)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    client = TestClient(server.app)
    assert client.get(f"/beacon/evidence/{TOKEN}").status_code == 503
    assert client.get(f"/beacon/evidence/{TOKEN}/verify").status_code == 503


def test_evidence_endpoint_requires_api_token_in_production(monkeypatch):
    monkeypatch.setenv("MIRAGE_ENV", "production")
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    client = TestClient(server.app)
    res = client.get(f"/beacon/evidence/{TOKEN}/verify")
    assert res.status_code == 503
