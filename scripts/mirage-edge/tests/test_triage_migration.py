"""
PR A — 0004 beacon triyaj migration yapısal doğrulaması.

PostgreSQL yokluğunda migration dosyasını parse eder ve sözleşmeyi doğrular:
  - beacon_triage tablosu var mı?
  - severity/action/confidence CHECK kısıtları var mı?
  - append-only trigger (UPDATE/DELETE yasak) var mı?
  - idempotent mi (if not exists / create or replace)?
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest


MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "0004_beacon_triage.sql"
)


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION.exists(), f"Migration not found: {MIGRATION}"


def test_table_created_idempotently():
    assert re.search(
        r"create\s+table\s+if\s+not\s+exists\s+public\.beacon_triage",
        sql(),
        re.IGNORECASE,
    )


def test_severity_and_action_check_constraints():
    text = sql()
    assert re.search(
        r"check\s*\(\s*severity\s+in\s*\(\s*'low'\s*,\s*'medium'\s*,\s*'high'\s*,\s*'critical'\s*\)",
        text,
        re.IGNORECASE,
    )
    assert re.search(
        r"check\s*\(\s*recommended_action\s+in\s*\(\s*'ignore'\s*,\s*'monitor'\s*,\s*'investigate'\s*,\s*'escalate'\s*\)",
        text,
        re.IGNORECASE,
    )


def test_confidence_bounds_check():
    assert re.search(
        r"check\s*\(\s*confidence\s*>=\s*0\s+and\s+confidence\s*<=\s*1\s*\)",
        sql(),
        re.IGNORECASE,
    )


def test_source_column_present():
    assert re.search(r"source\s+text\s+not\s+null", sql(), re.IGNORECASE)


def test_append_only_triggers():
    text = sql()
    assert re.search(
        r"create\s+or\s+replace\s+function\s+public\.forbid_triage_mutation",
        text,
        re.IGNORECASE,
    )
    assert re.search(
        r"create\s+trigger\s+trg_forbid_triage_update", text, re.IGNORECASE
    )
    assert re.search(
        r"create\s+trigger\s+trg_forbid_triage_delete", text, re.IGNORECASE
    )


def test_indexes_present():
    text = sql()
    assert re.search(r"idx_beacon_triage_token", text, re.IGNORECASE)
    assert re.search(r"idx_beacon_triage_created_at", text, re.IGNORECASE)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
