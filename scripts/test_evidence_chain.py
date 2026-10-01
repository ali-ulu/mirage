"""
MIRAGE — Kanıt zinciri (evidence chain) testleri.

Kapsam:
  1. Kanonikleştirme determinizmi (anahtar sırası bağımsız)
  2. Hash + HMAC doğruluğu (altın fixture'lar — TS ile parite kilidi)
  3. Zincir bütünlüğü: bozulmamış zincir "ok"
  4. Kurcalama: alan değişince record_hash mismatch
  5. Kopukluk: prev_hash yanlışsa red
  6. Sahte kayıt: HMAC yanlışsa red
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage.evidence import (  # noqa: E402
    GENESIS_HASH,
    build_evidence_record,
    canonical_json,
    compute_hmac,
    normalize_timestamp,
    record_hash,
    verify_chain,
    verify_hmac,
)

KEY = "test-key-0123456789abcdef"

# Altın fixture'lar: TS `evidence.ts` ile birebir aynı olmalı.
GOLDEN_1 = {
    "token": "550e8400-e29b-41d4-a716-446655440000",
    "ip": "203.0.113.42",
    "user_agent": "LibreOffice/7.5",
    "received_at": "2026-10-01T12:00:00.000Z",
    "chain_seq": 1,
    "prev_hash": GENESIS_HASH,
}
GOLDEN_1_HASH = "b306771dbc5659915d38ee89232b2b81d038d45c1161e1be218a6c56bb7933c7"
GOLDEN_1_HMAC = "962fcde9fa9a9a9aba0753228e3772c8db9fe9c994d14c6f962619e34415a9d7"

GOLDEN_2 = {
    "token": "550e8400-e29b-41d4-a716-446655440000",
    "ip": "198.51.100.7",
    "user_agent": "Excel/16.0",
    "received_at": "2026-10-01T12:05:00.000Z",
    "chain_seq": 2,
    "prev_hash": GOLDEN_1_HASH,
}
GOLDEN_2_HASH = "44f3aaaa150500bfe21c1f6c1304ca699ae45d519685334d8e2279f553ecd344"
GOLDEN_2_HMAC = "0a1b6e09a069b4559e3e715920ae0d05be27497df38bc66dad63382fddf6e112"


def _record(seq: int, prev: str, **overrides):
    base = {
        "token": "550e8400-e29b-41d4-a716-446655440000",
        "ip": "203.0.113.42",
        "user_agent": "LibreOffice/7.5",
        "received_at": f"2026-10-01T12:{seq:02d}:00.000Z",
        "chain_seq": seq,
        "prev_hash": prev,
    }
    base.update(overrides)
    return build_evidence_record(key=KEY, **base)


def _chain(n: int):
    records = []
    prev = GENESIS_HASH
    for seq in range(1, n + 1):
        rec = _record(seq, prev)
        records.append(rec)
        prev = rec["record_hash"]
    return records


# ---------------------------------------------------------------------------
# 1. Kanonikleştirme
# ---------------------------------------------------------------------------
def test_canonical_json_is_key_order_independent():
    shuffled = {k: GOLDEN_1[k] for k in reversed(list(GOLDEN_1.keys()))}
    assert canonical_json(shuffled) == canonical_json(GOLDEN_1)


def test_canonical_json_has_no_whitespace_and_sorted_keys():
    c = canonical_json(GOLDEN_1)
    assert " " not in c
    assert c.index("chain_seq") < c.index("ip") < c.index("token")


def test_canonical_json_ignores_non_canonical_fields():
    # opener_app gibi türetilmiş alanlar kanonik kayda girmemeli.
    with_extra = {**GOLDEN_1, "opener_app": "excel", "id": "abc"}
    assert canonical_json(with_extra) == canonical_json(GOLDEN_1)


# ---------------------------------------------------------------------------
# 2. Hash + HMAC (altın fixture paritesi)
# ---------------------------------------------------------------------------
def test_golden_record_hash_matches():
    assert record_hash(GOLDEN_1) == GOLDEN_1_HASH
    assert record_hash(GOLDEN_2) == GOLDEN_2_HASH


def test_golden_hmac_matches():
    assert compute_hmac(KEY, GOLDEN_1_HASH) == GOLDEN_1_HMAC
    assert compute_hmac(KEY, GOLDEN_2_HASH) == GOLDEN_2_HMAC


def test_build_evidence_record_matches_golden():
    rec = build_evidence_record(key=KEY, **GOLDEN_1)
    assert rec["record_hash"] == GOLDEN_1_HASH
    assert rec["hmac"] == GOLDEN_1_HMAC


def test_timestamp_normalized_to_canonical_utc():
    assert normalize_timestamp("2026-10-01T12:00:00.000Z") == "2026-10-01T12:00:00.000Z"
    # Postgres timestamptz gidiş-dönüşü aynı ana normalize olmalı.
    assert normalize_timestamp("2026-10-01T12:00:00+00:00") == "2026-10-01T12:00:00.000Z"
    assert normalize_timestamp("2026-10-01T15:00:00+03:00") == "2026-10-01T12:00:00.000Z"


def test_db_roundtrip_timestamp_still_matches_golden():
    """
    `received_at`, PostgreSQL `timestamptz`'e yazılıp `+00:00` biçiminde geri
    okunsa bile hash aynı kalmalı (aksi halde doğrulama yanlış 'kurcalanmış' der).
    """
    db_form = {**GOLDEN_1, "received_at": "2026-10-01T12:00:00+00:00"}
    assert record_hash(db_form) == GOLDEN_1_HASH


def test_verify_hmac_accepts_and_rejects():
    assert verify_hmac(KEY, GOLDEN_1_HASH, GOLDEN_1_HMAC)
    assert not verify_hmac(KEY, GOLDEN_1_HASH, "deadbeef")
    assert not verify_hmac(KEY, GOLDEN_1_HASH, "")
    assert not verify_hmac("wrong-key", GOLDEN_1_HASH, GOLDEN_1_HMAC)


# ---------------------------------------------------------------------------
# 3. Zincir bütünlüğü
# ---------------------------------------------------------------------------
def test_intact_chain_verifies_ok():
    result = verify_chain(_chain(5), KEY)
    assert result["ok"] is True
    assert result["checked"] == 5
    assert result["broken_at"] is None


def test_empty_chain_is_ok():
    result = verify_chain([], KEY)
    assert result["ok"] is True
    assert result["checked"] == 0


def test_chain_links_prev_hash_to_previous_record():
    records = _chain(3)
    assert records[0]["prev_hash"] == GENESIS_HASH
    assert records[1]["prev_hash"] == records[0]["record_hash"]
    assert records[2]["prev_hash"] == records[1]["record_hash"]


# ---------------------------------------------------------------------------
# 4. Kurcalama (tampering)
# ---------------------------------------------------------------------------
def test_modified_field_breaks_chain():
    records = _chain(3)
    records[1]["ip"] = "10.0.0.1"  # kurcalama
    result = verify_chain(records, KEY)
    assert result["ok"] is False
    assert result["broken_at"] == 2
    assert "record_hash mismatch" in result["reason"]


def test_modified_record_hash_breaks_chain():
    records = _chain(2)
    records[0]["record_hash"] = "f" * 64
    result = verify_chain(records, KEY)
    assert result["ok"] is False
    assert result["broken_at"] == 1


# ---------------------------------------------------------------------------
# 5. Kopukluk (broken link)
# ---------------------------------------------------------------------------
def test_broken_prev_hash_is_rejected():
    # İçsel olarak tutarlı (doğru hash + hmac) ama yanlış kayda bağlanan bir
    # kayıt: saldırgan kendi geçmişini uydurursa zincir kopukluğu yakalanır.
    records = _chain(3)
    forged_tail = build_evidence_record(
        key=KEY,
        token=GOLDEN_1["token"],
        ip=GOLDEN_1["ip"],
        user_agent=GOLDEN_1["user_agent"],
        received_at="2026-10-01T12:03:00.000Z",
        chain_seq=3,
        prev_hash="a" * 64,  # yanlış bağ
    )
    records[2] = forged_tail
    result = verify_chain(records, KEY)
    assert result["ok"] is False
    assert result["broken_at"] == 3
    assert "prev_hash" in result["reason"]


def test_deleted_middle_record_is_rejected():
    records = _chain(3)
    del records[1]  # ortadaki kayıt silindi
    result = verify_chain(records, KEY)
    assert result["ok"] is False
    assert result["broken_at"] == 3


# ---------------------------------------------------------------------------
# 6. Sahte kayıt (forged HMAC)
# ---------------------------------------------------------------------------
def test_forged_hmac_is_rejected():
    records = _chain(2)
    records[1]["hmac"] = "0" * 64
    result = verify_chain(records, KEY)
    assert result["ok"] is False
    assert result["broken_at"] == 2
    assert "hmac" in result["reason"]


def test_record_signed_with_wrong_key_is_rejected():
    records = _chain(1)
    forged = build_evidence_record(key="attacker-key", **GOLDEN_1)
    result = verify_chain([forged], KEY)
    assert result["ok"] is False
    assert "hmac" in result["reason"]
