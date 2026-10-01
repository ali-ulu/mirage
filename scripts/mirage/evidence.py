"""
MIRAGE — Kanıt zinciri (evidence chain) çekirdeği.

Bu modül, bir honeytoken beacon olayını sonradan değiştirilemez bir kanıt
kaydına dönüştürür. İki katman vardır:

  1. Hash zinciri: her kayıt, bir önceki kaydın `record_hash`'ini `prev_hash`
     olarak taşır. Böylece kayıtlar arasında kopmaz bir bağ oluşur.
  2. HMAC imzası: her `record_hash`, sunucu sırrıyla (`MIRAGE_EVIDENCE_HMAC_KEY`)
     imzalanır. Sırrı bilmeyen bir taraf yeni geçerli kayıt üretemez.

Kanonik alan seti (imzalanan kayıt):
    token, ip, user_agent, received_at, chain_seq, prev_hash

NOT: `opener_app` bilinçli olarak kanonik kayda DAHİL EDİLMEZ. O kolon,
PostgreSQL'de `generated always as` ile user_agent'tan türetilen bir görüntü
kolonudur; kanıtın kriptografik içeriğine dahil edilmesi gerekmez ve edilmesi
halinde DB trigger'ında hesaplanamaz (generated kolonlar BEFORE trigger'da
henüz NULL'dur). Türetilmiş kolonlar imzalanan kaydın dışında tutulur.

Kanonikleştirme: JSON, anahtarlar sıralı, boşluksuz, UTF-8 (ensure_ascii=False).
Bu, TypeScript karşılığı `scripts/mirage-edge/functions/beacon-receiver/evidence.ts`
ile BİREBİR aynı olmalıdır; parite `scripts/test_evidence_chain.py` içindeki
altın (golden) fixture'larla doğrulanır.
"""
from __future__ import annotations

import hashlib
import hmac as hmaclib
import json
from typing import Any, Iterable, Optional

# İlk kaydın prev_hash'i — sabit, belgelenmiş çapa.
GENESIS_HASH = "0" * 64

# İmzalanan (kanonik) alanlar ve sırası.
EVIDENCE_FIELDS: tuple[str, ...] = (
    "token",
    "ip",
    "user_agent",
    "received_at",
    "chain_seq",
    "prev_hash",
)


def canonical_json(record: dict[str, Any]) -> str:
    """
    Kanonik JSON: yalnızca kanonik alanlar, anahtarlar sıralı, boşluksuz,
    non-ASCII kaçırılmadan (ensure_ascii=False). TS tarafıyla parite zorunlu.
    """
    subset = {k: record.get(k) for k in EVIDENCE_FIELDS}
    return json.dumps(
        subset,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def record_hash(record: dict[str, Any]) -> str:
    """Kanonik kaydın SHA-256 özeti (hex)."""
    payload = canonical_json(record).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_hmac(key: str | bytes, record_hash_hex: str) -> str:
    """record_hash üzerinde HMAC-SHA256 (hex). Anahtar str ise UTF-8 kodlanır."""
    key_bytes = key.encode("utf-8") if isinstance(key, str) else key
    return hmaclib.new(key_bytes, record_hash_hex.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_hmac(key: str | bytes, record_hash_hex: str, expected_hmac: str) -> bool:
    """Sabit-zamanlı HMAC karşılaştırması."""
    if not expected_hmac:
        return False
    return hmaclib.compare_digest(compute_hmac(key, record_hash_hex), expected_hmac)


def build_evidence_record(
    *,
    token: str,
    ip: str,
    user_agent: str,
    received_at: str,
    chain_seq: int,
    prev_hash: str,
    key: str | bytes,
) -> dict[str, Any]:
    """
    Yeni bir kanıt kaydı üretir: prev_hash bağını kurar, record_hash ve hmac
    hesaplar. DB'ye tek seferde yazılacak alanları döndürür.
    """
    base = {
        "token": token,
        "ip": ip,
        "user_agent": user_agent,
        "received_at": received_at,
        "chain_seq": chain_seq,
        "prev_hash": prev_hash,
    }
    rh = record_hash(base)
    return {**base, "record_hash": rh, "hmac": compute_hmac(key, rh)}


def next_chain_position(head: Optional[dict[str, Any]]) -> tuple[int, str]:
    """
    Zincir başındaki (en yüksek chain_seq'li) kayda göre bir sonraki
    (chain_seq, prev_hash) çiftini döndürür. head None ise genesis.
    """
    if not head:
        return 1, GENESIS_HASH
    return int(head["chain_seq"]) + 1, str(head["record_hash"])


def verify_chain(records: Iterable[dict[str, Any]], key: str | bytes) -> dict[str, Any]:
    """
    Sıralı kanıt kayıtlarını doğrular.

    Döndürür:
        {"ok": bool, "checked": int, "broken_at": Optional[int], "reason": Optional[str]}

    Kontroller (her kayıt için):
      1. record_hash alanlardan yeniden hesaplanabilir mi? (kurcalama)
      2. prev_hash, bir önceki kaydın record_hash'ine eşit mi? (kopukluk)
      3. hmac, kayıtlı record_hash için geçerli mi? (sahte kayıt)
    """
    ordered = sorted(records, key=lambda r: int(r["chain_seq"]))
    prev = GENESIS_HASH
    checked = 0
    for r in ordered:
        checked += 1
        expected = record_hash(r)
        if expected != r.get("record_hash"):
            return {
                "ok": False,
                "checked": checked,
                "broken_at": int(r["chain_seq"]),
                "reason": "record_hash mismatch (record was modified)",
            }
        if r.get("prev_hash") != prev:
            return {
                "ok": False,
                "checked": checked,
                "broken_at": int(r["chain_seq"]),
                "reason": "prev_hash does not link to previous record",
            }
        if not verify_hmac(key, str(r["record_hash"]), str(r.get("hmac", ""))):
            return {
                "ok": False,
                "checked": checked,
                "broken_at": int(r["chain_seq"]),
                "reason": "hmac verification failed",
            }
        prev = str(r["record_hash"])
    return {"ok": True, "checked": checked, "broken_at": None, "reason": None}
