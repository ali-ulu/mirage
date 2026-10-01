"""
PR — Takım üyeliği yönetimi: store + FastAPI endpoint testleri.

Strateji:
  - Store testleri: supabase-py chain API'sini taklit eden in-memory mock ile
    (upsert/select/delete/limit).
  - Endpoint testleri: TestClient + enjekte edilmiş mock store
    (reset_team_store_for_testing).
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.team_store import TeamMembershipStore  # noqa: E402

USER = "00000000-0000-0000-0000-0000000000a1"
TEAM = "aaaaaaaa-0000-0000-0000-000000000001"
TEAM2 = "bbbbbbbb-0000-0000-0000-000000000002"


class _MockChain:
    def __init__(self, storage: dict, table: str):
        self.storage = storage
        self.table_name = table
        self._filters: list[tuple[str, object]] = []
        self._limit: int | None = None
        self._order: tuple[str, bool] | None = None
        self._op = None
        self._payload = None
        self._on_conflict = None

    def select(self, *_a):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def delete(self):
        self._op = "delete"
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
        rows = self.storage.setdefault(self.table_name, [])
        if self._op in ("insert", "upsert"):
            payload = dict(self._payload)
            if self._op == "upsert":
                keys = [k for k in (self._on_conflict or "").split(",") if k]
                for i, r in enumerate(rows):
                    if all(r.get(k) == payload.get(k) for k in keys):
                        rows[i] = {**r, **payload}
                        break
                else:
                    rows.append(payload)
            else:
                rows.append(payload)
            return type("R", (), {"data": [payload], "error": None})()
        if self._op == "delete":
            before = len(rows)
            self.storage[self.table_name] = [
                r
                for r in rows
                if not all(r.get(c) == v for c, v in self._filters)
            ]
            removed = before - len(self.storage[self.table_name])
            return type("R", (), {"data": [{}] * removed, "error": None})()
        # select
        result = list(rows)
        for col, val in self._filters:
            result = [r for r in result if r.get(col) == val]
        if self._order:
            col, desc = self._order
            result.sort(key=lambda r: str(r.get(col, "")), reverse=desc)
        if self._limit is not None:
            result = result[: self._limit]
        return type("R", (), {"data": result, "error": None})()


class MockSupabaseClient:
    def __init__(self):
        self.storage: dict[str, list] = {}

    def table(self, name):
        return _MockChain(self.storage, name)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
def test_add_and_get_role():
    store = TeamMembershipStore(client=MockSupabaseClient())
    store.add(user_id=USER, team_id=TEAM, role="owner")
    assert store.get_role(user_id=USER, team_id=TEAM) == "owner"
    assert store.is_member(user_id=USER, team_id=TEAM) is True
    assert store.is_member(user_id=USER, team_id=TEAM2) is False


def test_upsert_updates_role():
    store = TeamMembershipStore(client=MockSupabaseClient())
    store.add(user_id=USER, team_id=TEAM, role="member")
    store.add(user_id=USER, team_id=TEAM, role="admin")
    members = store.list_for_team(TEAM)
    assert len(members) == 1
    assert members[0].role == "admin"


def test_list_for_team_and_user():
    store = TeamMembershipStore(client=MockSupabaseClient())
    store.add(user_id=USER, team_id=TEAM)
    store.add(user_id=USER, team_id=TEAM2)
    assert len(store.list_for_user(USER)) == 2
    assert len(store.list_for_team(TEAM)) == 1


def test_remove_membership():
    store = TeamMembershipStore(client=MockSupabaseClient())
    store.add(user_id=USER, team_id=TEAM)
    assert store.remove(user_id=USER, team_id=TEAM) == 1
    assert store.get_role(user_id=USER, team_id=TEAM) is None
    assert store.remove(user_id=USER, team_id=TEAM) == 0


def test_invalid_uuid_rejected():
    store = TeamMembershipStore(client=MockSupabaseClient())
    for kwargs in (
        {"user_id": "not-a-uuid", "team_id": TEAM},
        {"user_id": USER, "team_id": "nope"},
    ):
        try:
            store.add(**kwargs)
            raise AssertionError("invalid uuid kabul edilmemeli")
        except ValueError:
            pass


def test_invalid_role_rejected():
    store = TeamMembershipStore(client=MockSupabaseClient())
    try:
        store.add(user_id=USER, team_id=TEAM, role="root")
        raise AssertionError("invalid role kabul edilmemeli")
    except ValueError:
        pass


def test_list_returns_empty_on_error():
    class Boom:
        def table(self, _n):
            raise RuntimeError("db down")

    store = TeamMembershipStore(client=Boom())
    assert store.list_for_team(TEAM) == []
    assert store.get_role(user_id=USER, team_id=TEAM) is None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
def _client():
    server.reset_team_store_for_testing(client=MockSupabaseClient())
    return TestClient(server.app)


def test_endpoint_add_list_get_delete():
    client = _client()
    r = client.post("/team/members", json={"user_id": USER, "team_id": TEAM, "role": "owner"})
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "owner"

    r = client.get(f"/team/{TEAM}/members")
    assert r.status_code == 200
    assert r.json()["count"] == 1

    r = client.get(f"/team/{TEAM}/members/{USER}")
    assert r.status_code == 200
    assert r.json()["role"] == "owner"

    r = client.delete(f"/team/{TEAM}/members/{USER}")
    assert r.status_code == 200
    assert r.json()["removed"] == 1

    r = client.get(f"/team/{TEAM}/members/{USER}")
    assert r.status_code == 404


def test_endpoint_invalid_uuid_422():
    client = _client()
    r = client.post("/team/members", json={"user_id": "bad", "team_id": TEAM})
    assert r.status_code == 422


def test_endpoint_delete_missing_404():
    client = _client()
    r = client.delete(f"/team/{TEAM}/members/{USER}")
    assert r.status_code == 404


def test_endpoint_503_when_unconfigured(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    server.reset_team_store_for_testing()
    client = TestClient(server.app)
    r = client.get(f"/team/{TEAM}/members")
    assert r.status_code == 503
    server.reset_team_store_for_testing()
