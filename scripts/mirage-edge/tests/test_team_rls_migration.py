"""
PR — 0008 tenant RLS migration yapısal doğrulaması.

PostgreSQL yokluğunda migration dosyasını parse eder:
  - üyelik tablosu + current_team_ids() helper var mı?
  - üç tenant tablosunda SELECT + INSERT policy'si var mı?
  - UPDATE/DELETE policy'si YOK mu (deny-by-default)?
  - service_role policy'leri korunuyor mu?
  - idempotent mi (drop policy if exists)?
Davranışsal doğrulama (yerel PostgreSQL + `set request.jwt.claim.sub`) ayrıca
yapılır; bkz. commit mesajı ve PR açıklaması.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "0008_team_rls.sql"
)

TENANT_TABLES = ("honeytokens", "prompt_canaries", "beacon_triage")


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION.exists(), f"Migration not found: {MIGRATION}"


def test_team_members_table_with_rls():
    text = sql()
    assert re.search(
        r"create\s+table\s+if\s+not\s+exists\s+public\.team_members", text, re.I
    )
    assert re.search(
        r"alter\s+table\s+public\.team_members\s+enable\s+row\s+level\s+security",
        text,
        re.I,
    )
    assert re.search(r"service_role_all_team_members", text)


def test_current_team_ids_helper_uses_jwt_sub():
    text = sql()
    assert re.search(r"function\s+public\.current_team_ids\s*\(", text, re.I)
    assert "request.jwt.claim.sub" in text
    assert re.search(r"returns\s+uuid\[\]", text, re.I)


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_tenant_read_and_insert_policies(table):
    text = sql()
    assert re.search(
        rf"create\s+policy\s+\"team_read_{table}\"\s+on\s+public\.{table}", text, re.I
    ), f"missing SELECT policy for {table}"
    assert re.search(
        rf"create\s+policy\s+\"team_insert_{table}\"\s+on\s+public\.{table}",
        text,
        re.I,
    ), f"missing INSERT policy for {table}"
    # Policy'ler authenticated'a ve team_id eşitliğine bağlı olmalı.
    assert re.search(r"for\s+select\s+to\s+authenticated", text, re.I)
    assert re.search(r"for\s+insert\s+to\s+authenticated", text, re.I)
    assert "current_team_ids()" in text


def test_no_update_or_delete_tenant_policies():
    # Deny-by-default: tenant tabloları için UPDATE/DELETE policy'si olmamalı.
    text = sql().lower()
    for table in TENANT_TABLES:
        assert f"for update to authenticated" not in text
        assert f"for delete to authenticated" not in text
        # Append-only zaten trigger ile korunuyor.
    assert "for all to authenticated" not in text


def test_service_role_policies_preserved():
    text = sql().lower()
    assert "service_role_all_team_members" in text
    # 0002/0005/0006'daki service_role policy'leri burada DROP EDİLMEMELİ.
    assert "drop policy if exists \"service_role_all_honeytokens\"" not in text
    assert "drop policy if exists \"service_role_all_prompt_canaries\"" not in text
    assert "drop policy if exists \"service_role_all_beacon_triage\"" not in text


def test_idempotent_drop_policy_guards():
    text = sql().lower()
    # Her create policy'den önce drop policy if exists olmalı.
    creates = len(re.findall(r"create\s+policy", text))
    drops = len(re.findall(r"drop\s+policy\s+if\s+exists", text))
    assert drops >= creates, f"drops={drops} creates={creates}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
