"""
MIRAGE — 0008 tenant RLS canlı davranışsal doğrulaması (opt-in).

`MIRAGE_PG_DSN` verilmezse (veya psycopg2 yoksa) testler atlanır; CI bu yüzden
yeşil kalır. Gerçek bir PostgreSQL (0001–0008 uygulanmış) verildiğinde
`authenticated` rolünü `request.jwt.claim.sub` ile taklit edip izolasyonu
doğrular:

  - authenticated yalnızca kendi takımının satırlarını görür,
  - yalnızca kendi takımına INSERT edebilir (başkasına / NULL'a → RLS hatası),
  - UPDATE/DELETE policy'si yok (0 satır etkilenir),
  - service_role tüm satırları görür,
  - JWT sub yoksa authenticated hiçbir satır görmez.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

DSN = os.environ.get("MIRAGE_PG_DSN")

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
pytestmark = pytest.mark.skipif(
    not DSN, reason="MIRAGE_PG_DSN not set (live DB verification is opt-in)"
)

USER_A = "00000000-0000-0000-0000-0000000000a1"
TEAM_A = "aaaaaaaa-0000-0000-0000-000000000001"
TEAM_B = "bbbbbbbb-0000-0000-0000-000000000002"


def _connect():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    return conn


def _count(cur, table: str) -> int:
    cur.execute(f"select count(*) from public.{table}")
    return cur.fetchone()[0]


@pytest.fixture()
def db():
    conn = _connect()
    cur = conn.cursor()
    # Şema hazır mı? (0008 uygulanmamışsa atla.)
    cur.execute("select to_regclass('public.team_members')")
    if cur.fetchone()[0] is None:
        conn.close()
        pytest.skip("0008 not applied (team_members missing)")
    # Temiz kurulum (superuser RLS'i baypas eder).
    cur.execute("truncate public.honeytokens, public.prompt_canaries, public.beacon_triage")
    cur.execute("delete from public.team_members")
    cur.execute(
        "insert into public.team_members (user_id, team_id, role) values (%s,%s,'owner')",
        (USER_A, TEAM_A),
    )
    yield conn, cur
    cur.execute("reset role")
    cur.execute("reset request.jwt.claim.sub")
    conn.close()


def _as_authenticated(cur, sub: str | None):
    cur.execute("set role authenticated")
    if sub:
        cur.execute("set request.jwt.claim.sub = %s", (sub,))
    else:
        cur.execute("reset request.jwt.claim.sub")


def _seed_three(cur):
    cur.execute(
        """insert into public.prompt_canaries (token, marker, context, team_id) values
           (%s,'M1','system_prompt',%s),(%s,'M2','system_prompt',%s),(%s,'M3','system_prompt',null)""",
        (str(uuid.uuid4()), TEAM_A, str(uuid.uuid4()), TEAM_B, str(uuid.uuid4())),
    )


def test_service_role_sees_all_teams(db):
    conn, cur = db
    _seed_three(cur)
    assert _count(cur, "prompt_canaries") == 3


def test_authenticated_sees_only_own_team(db):
    conn, cur = db
    _seed_three(cur)
    _as_authenticated(cur, USER_A)
    assert _count(cur, "prompt_canaries") == 1
    assert _count(cur, "team_members") == 1


def test_authenticated_cannot_insert_foreign_or_null_team(db):
    conn, cur = db
    _as_authenticated(cur, USER_A)
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        cur.execute(
            "insert into public.prompt_canaries (token, marker, context, team_id) values (%s,'X','system_prompt',%s)",
            (str(uuid.uuid4()), TEAM_B),
        )
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        cur.execute(
            "insert into public.prompt_canaries (token, marker, context, team_id) values (%s,'X','system_prompt',null)",
            (str(uuid.uuid4()),),
        )


def test_authenticated_insert_own_team_succeeds(db):
    conn, cur = db
    _as_authenticated(cur, USER_A)
    cur.execute(
        "insert into public.prompt_canaries (token, marker, context, team_id) values (%s,'X','system_prompt',%s)",
        (str(uuid.uuid4()), TEAM_A),
    )
    assert _count(cur, "prompt_canaries") == 1


def test_authenticated_cannot_update_or_delete(db):
    conn, cur = db
    cur.execute(
        "insert into public.prompt_canaries (token, marker, context, team_id) values (%s,'M1','system_prompt',%s)",
        (str(uuid.uuid4()), TEAM_A),
    )
    _as_authenticated(cur, USER_A)
    cur.execute("update public.prompt_canaries set label='x' where team_id=%s", (TEAM_A,))
    assert cur.rowcount == 0
    cur.execute("delete from public.prompt_canaries where team_id=%s", (TEAM_A,))
    assert cur.rowcount == 0


def test_authenticated_without_jwt_sees_nothing(db):
    conn, cur = db
    cur.execute(
        "insert into public.prompt_canaries (token, marker, context, team_id) values (%s,'M1','system_prompt',%s)",
        (str(uuid.uuid4()), TEAM_A),
    )
    _as_authenticated(cur, None)
    assert _count(cur, "prompt_canaries") == 0
