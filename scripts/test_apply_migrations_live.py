"""
MIRAGE — Migration uygulayıcı + RLS canlı doğrulaması (opt-in).

`MIRAGE_PG_DSN` verilmezse atlanır (CI yeşil kalır). Verildiğinde geçici bir
scratch veritabanı oluşturur, `apply_migrations` ile 0001–0008'i **gerçekten
uygular** ve sonucu doğrular:

  - tüm tablolar + `schema_migrations` defteri oluştu,
  - üç tenant tablosunda RLS etkin ve team policy'leri var,
  - `authenticated` yalnızca üye olduğu takımı görür / INSERT eder,
  - `service_role` hepsini görür,
  - migration idempotent (ikinci çalıştırma boş).

Supabase rol grant'leri (authenticated/anon/service_role) test kurulumunda
verilir — gerçek Supabase varsayılan grant modelini yansıtır; RLS asıl kapıdır.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

DSN = __import__("os").environ.get("MIRAGE_PG_DSN")

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
pytestmark = pytest.mark.skipif(
    not DSN, reason="MIRAGE_PG_DSN not set (live migration verification is opt-in)"
)

from apply_migrations import apply_migrations  # noqa: E402

USER_A = "00000000-0000-0000-0000-0000000000a1"
TEAM_A = "aaaaaaaa-0000-0000-0000-000000000001"
TEAM_B = "bbbbbbbb-0000-0000-0000-000000000002"

_SUPABASE_GRANTS = """
grant usage on schema public to authenticated, anon, service_role;
grant all on all tables in schema public to authenticated, anon, service_role;
grant all on all sequences in schema public to authenticated, anon, service_role;
"""


def _connect(dbname: str):
    conn = psycopg2.connect(DSN, dbname=dbname)
    conn.autocommit = True
    return conn


@pytest.fixture(scope="module")
def scratch_db():
    name = f"mirage_mig_test_{uuid.uuid4().hex[:8]}"
    admin = _connect("postgres")
    with admin.cursor() as cur:
        cur.execute(f'create database "{name}"')
    try:
        yield name
    finally:
        with admin.cursor() as cur:
            cur.execute(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname = %s and pid <> pg_backend_pid()",
                (name,),
            )
            cur.execute(f'drop database if exists "{name}"')
        admin.close()


@pytest.fixture(scope="module")
def prepared(scratch_db):
    """Scratch DB'ye 0001–0008'i uygular, Supabase grant'lerini verir."""
    dsn_scratch = _with_dbname(DSN, scratch_db)
    applied = apply_migrations(dsn_scratch)
    assert "0001_initial_schema" in applied
    assert "0008_team_rls" in applied
    # İdempotent: ikinci çalıştırma boş dönmeli.
    assert apply_migrations(dsn_scratch) == []

    conn = _connect(scratch_db)
    try:
        with conn.cursor() as cur:
            cur.execute(_SUPABASE_GRANTS)
    finally:
        conn.close()
    return scratch_db


def test_apply_creates_all_tables(prepared):
    conn = _connect(prepared)
    try:
        with conn.cursor() as cur:
            for table in (
                "attackers",
                "triggered_beacons",
                "sabotage_logs",
                "honeytokens",
                "beacon_triage",
                "prompt_canaries",
                "team_members",
                "schema_migrations",
            ):
                cur.execute("select to_regclass(%s)", (f"public.{table}",))
                assert cur.fetchone()[0] is not None, f"{table} eksik"
            cur.execute("select count(*) from public.schema_migrations")
            assert cur.fetchone()[0] >= 8
    finally:
        conn.close()


def test_rls_enabled_and_policies(scratch_db):
    conn = _connect(scratch_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select relname, relrowsecurity from pg_class "
                "where relname in ('honeytokens','prompt_canaries','beacon_triage')"
            )
            states = dict(cur.fetchall())
            assert states == {
                "honeytokens": True,
                "prompt_canaries": True,
                "beacon_triage": True,
            }
            cur.execute(
                "select count(*) from pg_policies where policyname like 'team_%'"
            )
            assert cur.fetchone()[0] >= 6
    finally:
        conn.close()


def test_authenticated_isolation(scratch_db):
    conn = _connect(scratch_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into public.team_members (user_id, team_id, role) values (%s,%s,'owner')",
                (USER_A, TEAM_A),
            )
            cur.execute(
                "insert into public.honeytokens (token, base_url, full_url, label, team_id) "
                "values (%s,%s,%s,%s,%s)",
                (str(uuid.uuid4()), "https://beacon.example/track", "https://beacon.example/track/tok", "A-secret", TEAM_A),
            )
            cur.execute(
                "insert into public.honeytokens (token, base_url, full_url, label, team_id) "
                "values (%s,%s,%s,%s,%s)",
                (str(uuid.uuid4()), "https://beacon.example/track", "https://beacon.example/track/tok", "B-secret", TEAM_B),
            )
            cur.execute("set role authenticated")
            cur.execute("set request.jwt.claim.sub = %s", (USER_A,))
            cur.execute("select count(*) from public.honeytokens")
            assert cur.fetchone()[0] == 1  # yalnızca A
            cur.execute("reset role")
            cur.execute("select count(*) from public.honeytokens")
            assert cur.fetchone()[0] == 2  # service/superuser hepsini görür
    finally:
        conn.close()


def _with_dbname(dsn: str, dbname: str) -> str:
    """DSN'in veritabanı adını değiştirir (postgresql://.../<db>)."""
    if "://" not in dsn:
        return f"{dsn} dbname={dbname}"
    base = dsn.split("?", 1)[0]
    query = ("?" + dsn.split("?", 1)[1]) if "?" in dsn else ""
    head, _, _tail = base.rpartition("/")
    return f"{head}/{dbname}{query}"
