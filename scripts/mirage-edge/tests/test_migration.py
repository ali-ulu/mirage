"""
MIRAGE Task 03 — SQL Migration syntax + mantık doğrulaması.

PostgreSQL yokluğunda, migration dosyasını parse edip temel yapısal
doğrulamalar yapar:
  - 3 tablo da var mı?
  - Trigger fonksiyonları var mı?
  - RLS policy'leri var mı?
  - Index'ler tanımlı mı?
  - FORBIDDEN column'lar yok mu? (mac_address, process_info gibi edge
    function'da yasaklı alanlar DB şemasında da olmamalı)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest


MIGRATION_PATH = Path(__file__).resolve().parent.parent / "migrations" / "0001_initial_schema.sql"
MIGRATION_PATH_2 = Path(__file__).resolve().parent.parent / "migrations" / "0002_honeytokens.sql"


def read_migration() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8") + "\n\n" + MIGRATION_PATH_2.read_text(encoding="utf-8")


def test_migration_file_exists():
    assert MIGRATION_PATH.exists(), f"Migration file not found: {MIGRATION_PATH}"


def test_three_main_tables_exist():
    sql = read_migration()
    for table in ("attackers", "triggered_beacons", "sabotage_logs"):
        pattern = rf"create\s+table\s+if\s+not\s+exists\s+public\.{table}"
        assert re.search(pattern, sql, re.IGNORECASE), (
            f"Tablo {table} migration'da yok"
        )


def test_no_machine_side_data_columns():
    """
    DB şeması edge function'ın yasakladığı verileri tutmamalı.
    Bu kolonlar olsaydı, MIRAGE kurban makinede kod çalıştırarak veri topluyor demektir.
    """
    sql = read_migration().lower()
    forbidden_columns = [
        "mac_address",
        "process_info",
        "local_files",
        "shell_output",
        "powershell_output",
        "cmd_output",
        "env_vars",
        "registry",
        "screenshot",
        "clipboard",
        "keylog",
        "credentials",
    ]
    # Kolon adı geçiyor mu diye regex ile tara
    for col in forbidden_columns:
        # column definition: <col_name> <type>
        pattern = rf"\b{col}\s+(text|jsonb|varchar|integer|inet|uuid)"
        assert not re.search(pattern, sql), (
            f"Yasaklı kolon '{col}' migration'da tanımlı — "
            "MIRAGE makine manipülasyon verisi toplayamaz"
        )


def test_rls_enabled_on_all_tables():
    sql = read_migration()
    for table in ("attackers", "triggered_beacons", "sabotage_logs"):
        pattern = rf"alter\s+table\s+public\.{table}\s+enable\s+row\s+level\s+security"
        assert re.search(pattern, sql, re.IGNORECASE), (
            f"RLS {table} tablosunda aktif değil"
        )


def test_service_role_policies_exist():
    sql = read_migration()
    # En az 3 policy olmalı (her tablo için service_role_all)
    matches = re.findall(
        r"create\s+policy\s+\"service_role_all_\w+\"\s+on\s+public\.\w+",
        sql, re.IGNORECASE
    )
    assert len(matches) >= 3, f"Sadece {len(matches)} service_role policy var, en az 3 olmalı"


def test_trigger_functions_exist():
    sql = read_migration()
    for fn in ("upsert_attacker_on_beacon", "log_beacon_event"):
        pattern = rf"create\s+or\s+replace\s+function\s+public\.{fn}"
        assert re.search(pattern, sql, re.IGNORECASE), (
            f"Trigger fonksiyonu {fn} yok"
        )


def test_triggers_attached():
    sql = read_migration()
    for trig in ("trg_upsert_attacker", "trg_log_beacon"):
        pattern = rf"create\s+trigger\s+{trig}"
        assert re.search(pattern, sql, re.IGNORECASE), f"Trigger {trig} yok"


def test_index_on_received_at():
    """received_at index'i dashboard'un son aktivite sorguları için kritik."""
    sql = read_migration()
    assert re.search(
        r"idx_beacons_received_at\s+on\s+public\.triggered_beacons",
        sql, re.IGNORECASE
    )


def test_index_on_token():
    """Token bazlı lookup için index."""
    sql = read_migration()
    assert re.search(
        r"idx_beacons_token\s+on\s+public\.triggered_beacons",
        sql, re.IGNORECASE
    )


def test_opener_app_generated_column():
    """opener_app otomatik tespit kolonu olmalı."""
    sql = read_migration()
    assert re.search(
        r"opener_app\s+text\s+generated\s+always\s+as",
        sql, re.IGNORECASE
    )
    # En azından libreoffice ve excel tespiti olmalı
    assert "libreoffice" in sql.lower()
    assert "excel" in sql.lower()


def test_attackers_unique_ip():
    """Aynı IP birden fazla satır olamaz — unique constraint."""
    sql = read_migration()
    assert re.search(
        r"unique\s*\(\s*ip\s*\)",
        sql, re.IGNORECASE
    )


def test_attackers_hit_count_default_one():
    sql = read_migration()
    assert re.search(
        r"hit_count\s+integer\s+not\s+null\s+default\s+1",
        sql, re.IGNORECASE
    )


def test_anon_role_has_no_policies():
    """Anon kullanıcının tablolara erişimi olmamalı."""
    sql = read_migration()
    # 'to anon' policy olmamalı
    assert not re.search(r"\bto\s+anon\b", sql, re.IGNORECASE), (
        "Anon role için policy tanımlı — güvenlik açığı"
    )
    # Policy clause'unda 'to public' (PostgreSQL'de herkes anlamına gelir) olmamalı.
    # 'public.tablo_adi' şema referansları false positive vermemesi için
    # policy clause regex ile yakala.
    policy_clauses = re.findall(
        r"create\s+policy\s+\"[^\"]+\"\s+on\s+public\.\w+\s+for\s+\w+\s+to\s+(\w+)",
        sql, re.IGNORECASE
    )
    for role in policy_clauses:
        assert role.lower() != "anon", f"Anon role policy'si var: {role}"
        assert role.lower() != "public", (
            f"'to public' policy'si var — herkes erişebilir. Role: {role}"
        )


def test_security_definer_on_triggers():
    """Trigger fonksiyonları SECURITY DEFINER olmalı (RLS'i bypass için)."""
    sql = read_migration()
    # Her trigger fonksiyonu security definer içermeli
    fn_blocks = re.findall(
        r"create\s+or\s+replace\s+function\s+public\.\w+\(\).*?as\s+\$\$.*?\$\$\s*;",
        sql, re.IGNORECASE | re.DOTALL
    )
    assert len(fn_blocks) >= 2
    for block in fn_blocks:
        assert "security definer" in block.lower(), (
            "Trigger fonksiyonu SECURITY DEFINER değil — RLS bypass edemez"
        )


def test_comments_document_purpose():
    sql = read_migration()
    for table in ("attackers", "triggered_beacons", "sabotage_logs"):
        pattern = rf"comment\s+on\s+table\s+public\.{table}\s+is"
        assert re.search(pattern, sql, re.IGNORECASE), f"Comment yok: {table}"


# =============================================================================
# honeytokens tablosu (Task 01 production)
# =============================================================================
def test_honeytokens_table_exists():
    sql = read_migration()
    assert re.search(
        r"create\s+table\s+if\s+not\s+exists\s+public\.honeytokens",
        sql, re.IGNORECASE
    ), "honeytokens tablosu migration'da yok"


def test_honeytokens_token_unique():
    sql = read_migration()
    # token uuid not null unique olmalı
    assert re.search(
        r"token\s+uuid\s+not\s+null\s+unique",
        sql, re.IGNORECASE
    )


def test_honeytokens_rls_enabled():
    sql = read_migration()
    assert re.search(
        r"alter\s+table\s+public\.honeytokens\s+enable\s+row\s+level\s+security",
        sql, re.IGNORECASE
    )


def test_honeytokens_has_team_id_for_multitenancy():
    """SaaS için team_id kolonu olmalı (multi-tenant)."""
    sql = read_migration()
    assert re.search(r"team_id\s+uuid", sql, re.IGNORECASE)


def test_honeytokens_has_triggered_count():
    """Beacon geldiğinde artırılacak sayaç."""
    sql = read_migration()
    assert re.search(
        r"triggered_count\s+integer\s+not\s+null\s+default\s+0",
        sql, re.IGNORECASE
    )


def test_honeytokens_has_update_trigger():
    """triggered_beacons insert'te honeytokens satırı güncellensin."""
    sql = read_migration()
    assert re.search(
        r"create\s+or\s+replace\s+function\s+public\.update_honeytoken_on_beacon",
        sql, re.IGNORECASE
    )
    assert re.search(
        r"create\s+trigger\s+trg_update_honeytoken",
        sql, re.IGNORECASE
    )


def test_honeytokens_no_machine_side_data():
    """honeytokens tablosu da makine manipülasyon verisi içermemeli."""
    sql = read_migration().lower()
    for col in ("mac_address", "process_info", "local_files", "shell_output"):
        pattern = rf"\b{col}\s+(text|jsonb|varchar|integer|inet|uuid)"
        assert not re.search(pattern, sql), (
            f"Yasaklı kolon '{col}' honeytokens migration'ında"
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
