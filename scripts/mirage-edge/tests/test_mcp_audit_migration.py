"""
MIRAGE — 0009 MCP denetim migration yapısal testleri.

Gerçek DB'ye bağlanmadan migration dosyasının sözleşmesini doğrular:
tablo tanımı, append-only trigger'ları, RLS politikası ve indeksler.
Davranışsal doğrulama yerel PostgreSQL'de ayrıca yapılır.
"""
from __future__ import annotations

from pathlib import Path

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "0009_mcp_audit.sql"


def _sql() -> str:
    return MIGRATION.read_text()


def test_migration_file_exists():
    assert MIGRATION.exists()


def test_creates_mcp_audit_table():
    sql = _sql().lower()
    assert "create table if not exists public.mcp_audit" in sql


def test_has_core_columns():
    sql = _sql().lower()
    for column in ("occurred_at", "actor", "server", "tool", "allowed", "reason", "risk_score", "risk_level"):
        assert column in sql, f"eksik sütun: {column}"


def test_risk_level_constrained():
    """risk_level tek geçerli değer kümesinde olmalı."""
    sql = _sql().lower()
    assert "check (risk_level in ('low', 'medium', 'high', 'critical'))" in sql


def test_append_only_triggers_present():
    """UPDATE ve DELETE yasaklanmalı — kanıt bütünlüğü için."""
    sql = _sql().lower()
    assert "trg_forbid_mcp_audit_update" in sql
    assert "trg_forbid_mcp_audit_delete" in sql
    assert "before update on public.mcp_audit" in sql
    assert "before delete on public.mcp_audit" in sql


def test_mutation_raises_exception():
    """Trigger gerçekten exception yükseltmeli, sessizce geçmemeli."""
    sql = _sql().lower()
    assert "raise exception" in sql
    assert "is append-only" in sql


def test_rls_enabled_and_service_role_only():
    sql = _sql().lower()
    assert "enable row level security" in sql
    assert "service_role_all_mcp_audit" in sql
    assert "to service_role" in sql


def test_indexes_for_dashboard_queries():
    """Dashboard sorguları occurred_at ve risk_level'a göre sıralar."""
    sql = _sql().lower()
    assert "idx_mcp_audit_occurred_at" in sql
    assert "idx_mcp_audit_risk_level" in sql
    assert "idx_mcp_audit_server" in sql


def test_idempotent():
    """Migration tekrar çalıştırılabilir olmalı."""
    sql = _sql().lower()
    assert sql.count("create table if not exists") >= 1
    assert "drop policy if exists" in sql
    assert "drop trigger if exists" in sql
    assert "create or replace function" in sql


def test_has_explanatory_comment():
    """Migration neden bu tabloya ihtiyaç duyulduğunu belgelemeli."""
    sql = _sql()
    assert "restart" in sql.lower()
    assert "append-only" in sql.lower()