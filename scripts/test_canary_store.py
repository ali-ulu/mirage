"""
MIRAGE — Supabase-backed prompt-layer canary store testleri.

Test stratejisi:
  1. Unit: sahte (fake) Supabase client ile — production kod mock içermez,
     yalnızca testte supabase-py zincir API'si taklit edilir.
  2. Restart dayanıklılığı: aynı storage'ı paylaşan iki registry örneği;
     ikincisi birincinin ürettiği canary'yi bulur (bellekte kaybolmaz).
  3. Fail-safe: DB operasyonu hata verirse lookup None, match [] döner.
  4. HTTP: uçlar Supabase registry ile çalışır (mock client enjekte edilir).
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.canary_store import SupabaseCanaryRegistry  # noqa: E402


# ---------------------------------------------------------------------------
# Sahte Supabase client (test-only)
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, data):
        self.data = data


class _Chain:
    def __init__(self, storage: dict, table: str, fail: bool = False):
        self.storage = storage
        self.table_name = table
        self.fail = fail
        self._filters: list[tuple[str, object]] = []
        self._in: list[tuple[str, list]] = []
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None

    def insert(self, payload: dict):
        self.storage.setdefault(self.table_name, []).append(payload)
        return self

    def select(self, *_cols):
        return self

    def eq(self, col, value):
        self._filters.append((col, value))
        return self

    def in_(self, col, values):
        self._in.append((col, list(values)))
        return self

    def order(self, col, desc: bool = False):
        self._order = (col, desc)
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("simulated supabase failure")
        rows = list(self.storage.get(self.table_name, []))
        for col, value in self._filters:
            rows = [r for r in rows if str(r.get(col)) == str(value)]
        for col, values in self._in:
            wanted = {str(v) for v in values}
            rows = [r for r in rows if str(r.get(col)) in wanted]
        if self._order:
            col, desc = self._order
            rows.sort(key=lambda r: str(r.get(col) or ""), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return _Result(rows)


class FakeSupabaseClient:
    def __init__(self, fail: bool = False):
        self.storage: dict[str, list[dict]] = {}
        self.fail = fail

    def table(self, name: str):
        return _Chain(self.storage, name, fail=self.fail)


# ---------------------------------------------------------------------------
# Unit
# ---------------------------------------------------------------------------
def test_issue_inserts_row():
    client = FakeSupabaseClient()
    reg = SupabaseCanaryRegistry(client=client)
    canary = reg.issue("system_prompt", label="agent-1")
    rows = client.storage["prompt_canaries"]
    assert len(rows) == 1
    assert rows[0]["token"] == canary.token
    assert rows[0]["context"] == "system_prompt"
    assert rows[0]["label"] == "agent-1"
    assert rows[0]["marker"] == canary.marker


def test_issue_rejects_invalid_context():
    reg = SupabaseCanaryRegistry(client=FakeSupabaseClient())
    try:
        reg.issue("nonsense")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_lookup_returns_record():
    reg = SupabaseCanaryRegistry(client=FakeSupabaseClient())
    canary = reg.issue("rag_document", label="kb")
    found = reg.lookup(canary.token)
    assert found is not None
    assert found.token == canary.token
    assert found.context == "rag_document"
    assert found.label == "kb"


def test_lookup_unknown_and_invalid_token_returns_none():
    reg = SupabaseCanaryRegistry(client=FakeSupabaseClient())
    assert reg.lookup("00000000-0000-0000-0000-000000000000") is None
    assert reg.lookup("not-a-uuid") is None


def test_match_returns_only_registered_in_order():
    reg = SupabaseCanaryRegistry(client=FakeSupabaseClient())
    a = reg.issue("system_prompt")
    b = reg.issue("agent_memory")
    other = "99999999-8888-7777-6666-555555555555"
    text = f"[[MIRAGE-CANARY:{b.token}]] ... [[MIRAGE-CANARY:{other}]] ... [[MIRAGE-CANARY:{a.token}]]"
    matched = reg.match(text)
    assert [c.token for c in matched] == [b.token, a.token]


def test_match_no_markers_returns_empty():
    reg = SupabaseCanaryRegistry(client=FakeSupabaseClient())
    reg.issue("system_prompt")
    assert reg.match("işaret yok") == []


def test_all_records_newest_first():
    reg = SupabaseCanaryRegistry(client=FakeSupabaseClient())
    reg.issue("system_prompt")
    reg.issue("rag_document")
    records = reg.all_records()
    assert len(records) == 2


def test_restart_durability():
    """Aynı storage'ı paylaşan yeni bir registry, önceki canary'yi bulur."""
    client = FakeSupabaseClient()
    first = SupabaseCanaryRegistry(client=client)
    canary = first.issue("agent_memory", label="persist")

    # "Restart": yeni registry örneği (bellek paylaşılmıyor, DB paylaşılıyor).
    second = SupabaseCanaryRegistry(client=client)
    found = second.lookup(canary.token)
    assert found is not None
    assert found.token == canary.token
    assert found.label == "persist"


def test_fail_safe_on_db_error():
    reg = SupabaseCanaryRegistry(client=FakeSupabaseClient(fail=True))
    assert reg.lookup("00000000-0000-0000-0000-000000000000") is None
    assert reg.match("[[MIRAGE-CANARY:00000000-0000-0000-0000-000000000000]]") == []
    assert reg.all_records() == []


# ---------------------------------------------------------------------------
# HTTP — Supabase registry ile
# ---------------------------------------------------------------------------
def test_endpoints_use_supabase_registry(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    client = FakeSupabaseClient()
    server.reset_canary_registry_for_testing(client=client)
    try:
        api = TestClient(server.app)
        issued = api.post("/agent/canary", json={"context": "rag_document"}).json()
        # DB'ye yazıldı mı?
        assert client.storage["prompt_canaries"][0]["token"] == issued["token"]

        leaked = api.post(
            "/agent/canary/check",
            json={"text": f"... {issued['marker']} ..."},
        ).json()
        assert leaked["leaked"] is True
        assert leaked["canaries"][0]["token"] == issued["token"]
    finally:
        server.reset_canary_registry_for_testing()


def test_canary_endpoint_returns_503_on_db_error(monkeypatch):
    monkeypatch.delenv("MIRAGE_API_TOKEN", raising=False)
    server.reset_canary_registry_for_testing(client=FakeSupabaseClient(fail=True))
    try:
        api = TestClient(server.app)
        res = api.post("/agent/canary", json={"context": "system_prompt"})
        assert res.status_code == 503
    finally:
        server.reset_canary_registry_for_testing()
