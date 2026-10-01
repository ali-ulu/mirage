"""
PR C — Üretim secret yapılandırması testleri.

Kapsam:
  - validate_production_env: kanıt imza anahtarı zorunlu mu?
  - validate_llm_env: LLM seçim tutarlılığı (opsiyonel ama doğru yapılandırılmalı)
  - fail_fast_on_missing_env: production'da çöker, dev'de uyarır
  - resolve_evidence_key: env -> dry-run -> boş sözleşmesi (TS ile aynı)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import env as env_mod  # noqa: E402
from mirage.evidence import resolve_evidence_key  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for var in (
        "MIRAGE_ENV",
        "MIRAGE_EVIDENCE_HMAC_KEY",
        "MIRAGE_EDGE_DRY_RUN",
        "MIRAGE_LLM_PROVIDER",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


# ---------------------------------------------------------------------------
# validate_production_env
# ---------------------------------------------------------------------------
def test_production_requires_evidence_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc")
    missing = env_mod.validate_production_env()
    assert "MIRAGE_EVIDENCE_HMAC_KEY" in missing


def test_production_ok_when_all_set(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc")
    monkeypatch.setenv("MIRAGE_EVIDENCE_HMAC_KEY", "k")
    assert env_mod.validate_production_env() == []


# ---------------------------------------------------------------------------
# validate_llm_env
# ---------------------------------------------------------------------------
def test_llm_env_unset_is_ok():
    assert env_mod.validate_llm_env() == []


def test_llm_env_none_and_auto_are_ok(monkeypatch):
    monkeypatch.setenv("MIRAGE_LLM_PROVIDER", "none")
    assert env_mod.validate_llm_env() == []
    monkeypatch.setenv("MIRAGE_LLM_PROVIDER", "auto")
    assert env_mod.validate_llm_env() == []


def test_llm_env_invalid_provider(monkeypatch):
    monkeypatch.setenv("MIRAGE_LLM_PROVIDER", "banana")
    errors = env_mod.validate_llm_env()
    assert len(errors) == 1
    assert "invalid" in errors[0]


def test_llm_env_openai_requires_key(monkeypatch):
    monkeypatch.setenv("MIRAGE_LLM_PROVIDER", "openai")
    assert any("OPENAI_API_KEY" in e for e in env_mod.validate_llm_env())
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert env_mod.validate_llm_env() == []


def test_llm_env_anthropic_requires_key(monkeypatch):
    monkeypatch.setenv("MIRAGE_LLM_PROVIDER", "anthropic")
    assert any("ANTHROPIC_API_KEY" in e for e in env_mod.validate_llm_env())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert env_mod.validate_llm_env() == []


# ---------------------------------------------------------------------------
# fail_fast_on_missing_env
# ---------------------------------------------------------------------------
def test_fail_fast_exits_in_production_when_missing(monkeypatch):
    monkeypatch.setenv("MIRAGE_ENV", "production")
    with pytest.raises(SystemExit):
        env_mod.fail_fast_on_missing_env()


def test_fail_fast_exits_in_production_on_bad_llm(monkeypatch):
    monkeypatch.setenv("MIRAGE_ENV", "production")
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc")
    monkeypatch.setenv("MIRAGE_EVIDENCE_HMAC_KEY", "k")
    monkeypatch.setenv("MIRAGE_LLM_PROVIDER", "openai")  # anahtar yok
    with pytest.raises(SystemExit):
        env_mod.fail_fast_on_missing_env()


def test_fail_fast_warns_in_development(monkeypatch):
    with pytest.warns(RuntimeWarning):
        env_mod.fail_fast_on_missing_env()


def test_fail_fast_noop_when_production_complete(monkeypatch):
    monkeypatch.setenv("MIRAGE_ENV", "production")
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc")
    monkeypatch.setenv("MIRAGE_EVIDENCE_HMAC_KEY", "k")
    env_mod.fail_fast_on_missing_env()  # çökmemeli


# ---------------------------------------------------------------------------
# resolve_evidence_key
# ---------------------------------------------------------------------------
def test_resolve_key_uses_env(monkeypatch):
    monkeypatch.setenv("MIRAGE_EVIDENCE_HMAC_KEY", "  secret  ")
    assert resolve_evidence_key() == "secret"


def test_resolve_key_dry_run_local(monkeypatch):
    monkeypatch.setenv("MIRAGE_EDGE_DRY_RUN", "true")
    assert resolve_evidence_key() == "mirage-local-dry-run-evidence-key"


def test_resolve_key_empty_in_production(monkeypatch):
    monkeypatch.setenv("MIRAGE_ENV", "production")
    monkeypatch.setenv("MIRAGE_EDGE_DRY_RUN", "true")  # prod'da dry-run yok
    assert resolve_evidence_key() == ""
