"""
0005 prompt_canaries migration yapısal doğrulaması.

PostgreSQL yokluğunda migration dosyasını parse eder ve sözleşmeyi doğrular:
  - prompt_canaries tablosu var mı?
  - context CHECK kısıtı var mı?
  - token unique mi?
  - append-only trigger (UPDATE/DELETE yasak) var mı?
  - RLS policy (service_role) var mı?
  - idempotent mi (if not exists / create or replace / drop ... if exists)?
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest


MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "0005_prompt_canaries.sql"
)


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION.exists(), f"Migration not found: {MIGRATION}"


def test_table_created_idempotently():
    assert re.search(
        r"create\s+table\s+if\s+not\s+exists\s+public\.prompt_canaries",
        sql(),
        re.IGNORECASE,
    )


def test_token_unique():
    assert re.search(r"token\s+uuid\s+not\s+null\s+unique", sql(), re.IGNORECASE)


def test_context_check_constraint():
    assert re.search(
        r"check\s*\(\s*context\s+in\s*\(\s*'system_prompt'\s*,\s*'rag_document'\s*,\s*'agent_memory'\s*\)",
        sql(),
        re.IGNORECASE,
    )


def test_marker_and_label_columns():
    text = sql()
    assert re.search(r"marker\s+text\s+not\s+null", text, re.IGNORECASE)
    assert re.search(r"label\s+text\s+not\s+null", text, re.IGNORECASE)


def test_rls_and_service_role_policy():
    text = sql()
    assert re.search(
        r"alter\s+table\s+public\.prompt_canaries\s+enable\s+row\s+level\s+security",
        text,
        re.IGNORECASE,
    )
    assert re.search(
        r"create\s+policy\s+\"service_role_all_prompt_canaries\"", text, re.IGNORECASE
    )


def test_append_only_triggers():
    text = sql()
    assert re.search(
        r"create\s+or\s+replace\s+function\s+public\.forbid_canary_mutation",
        text,
        re.IGNORECASE,
    )
    assert re.search(
        r"create\s+trigger\s+trg_forbid_canary_update", text, re.IGNORECASE
    )
    assert re.search(
        r"create\s+trigger\s+trg_forbid_canary_delete", text, re.IGNORECASE
    )


def test_indexes_present():
    text = sql()
    assert re.search(r"idx_prompt_canaries_token", text, re.IGNORECASE)
    assert re.search(r"idx_prompt_canaries_created_at", text, re.IGNORECASE)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
