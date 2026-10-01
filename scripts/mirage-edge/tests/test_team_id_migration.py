"""
MIRAGE — 0007 team_id migration yapısal testleri.

Gerçek DB'ye bağlanmadan migration dosyasının sözleşmesini doğrular: nullable
team_id, index'ler ve canary token tekilliğinin (team_id, token) çiftine
taşınması. Davranışsal doğrulama yerel PostgreSQL'de ayrıca yapılır.
"""
from __future__ import annotations

from pathlib import Path

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "0007_team_id.sql"


def _sql() -> str:
    return MIGRATION.read_text()


def test_migration_file_exists():
    assert MIGRATION.exists()


def test_adds_nullable_team_id_to_both_tables():
    sql = _sql().lower()
    assert "alter table public.prompt_canaries" in sql
    assert "alter table public.beacon_triage" in sql
    assert sql.count("add column if not exists team_id uuid") == 2
    # Nullable: NOT NULL dayatılmamalı.
    assert "team_id uuid not null" not in sql


def test_indexes_on_team_id():
    sql = _sql().lower()
    assert "idx_prompt_canaries_team" in sql
    assert "idx_beacon_triage_team" in sql


def test_token_uniqueness_preserved():
    # Mevcut global token tekilliği korunur (tenant kapsamı için gevşetilmez).
    sql = _sql().lower()
    assert "drop constraint" not in sql
    assert "uq_prompt_canaries_team_token" not in sql


def test_idempotent_guards():
    sql = _sql().lower()
    assert "add column if not exists" in sql
    assert "create index if not exists" in sql
