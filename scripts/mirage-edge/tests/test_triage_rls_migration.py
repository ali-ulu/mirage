"""
PR — 0006 beacon_triage RLS migration yapısal doğrulaması.

PostgreSQL yokluğunda migration dosyasını parse eder:
  - RLS etkinleştiriliyor mu?
  - yalnızca service_role policy'si mi var?
  - idempotent mi (drop policy if exists / enable row level security)?
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest


MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "0006_beacon_triage_rls.sql"
)


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION.exists(), f"Migration not found: {MIGRATION}"


def test_enables_row_level_security():
    assert re.search(
        r"alter\s+table\s+public\.beacon_triage\s+enable\s+row\s+level\s+security",
        sql(),
        re.IGNORECASE,
    )


def test_service_role_policy_present_and_idempotent():
    text = sql()
    assert re.search(
        r"drop\s+policy\s+if\s+exists\s+\"service_role_all_beacon_triage\"",
        text,
        re.IGNORECASE,
    )
    assert re.search(
        r"create\s+policy\s+\"service_role_all_beacon_triage\"\s+on\s+public\.beacon_triage",
        text,
        re.IGNORECASE,
    )


def test_policy_scoped_to_service_role_only():
    text = sql()
    # Policy yalnızca service_role'e verilmeli; anon/authenticated'a verilmemeli.
    assert re.search(r"for\s+all\s+to\s+service_role", text, re.IGNORECASE)
    assert not re.search(r"to\s+(anon|authenticated|public)\b", text, re.IGNORECASE)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
