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
`received_at` önce kanonik UTC ISO-8601 biçimine normalize edilir (bkz.
`normalize_timestamp`), böylece Postgres `timestamptz` gidiş-dönüşünden sonra da
aynı hash üretilir. Bu, TypeScript karşılığı
`scripts/mirage-edge/functions/beacon-receiver/evidence.ts` ile BİREBİR aynı
olmalıdır; parite `scripts/test_evidence_chain.py` içindeki altın (golden)
fixture'larla doğrulanır.
"""
from __future__ import annotations

import hashlib
import hmac as hmaclib
import json
from datetime import datetime, timezone
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


def normalize_timestamp(value: str) -> str:
    """
    Bir timestamp'i kanonik UTC ISO-8601 biçimine getirir: milisaniye hassasiyet,
    `Z` son eki (ör. "2026-10-01T12:00:00.000Z").

    Gerekçe: `received_at`, PostgreSQL `timestamptz`'e yazılıp geri okununca
    biçim değişir (`...000Z` -> `...+00:00`). Hash kanonik biçim üzerinden
    hesaplandığı için ham string ile DB değeri eşleşmez ve doğrulama yanlış
    şekilde "kurcalanmış" derdi. Değer normalize edilerek aynı an her iki
    biçimde de aynı hash'i üretir. TS karşılığı `normalizeTimestamp` ile birebir.
    """
    s = str(value)
    iso = s[:-1] + "+00:00" if s.endswith("Z") else s
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def canonical_json(record: dict[str, Any]) -> str:
    """
    Kanonik JSON: yalnızca kanonik alanlar, anahtarlar sıralı, boşluksuz,
    non-ASCII kaçırılmadan (ensure_ascii=False). TS tarafıyla parite zorunlu.

    `received_at` önce kanonik UTC biçimine normalize edilir (bkz.
    `normalize_timestamp`), böylece DB'den okunan eşdeğer zaman damgaları da
    aynı hash'i üretir.
    """
    subset = {k: record.get(k) for k in EVIDENCE_FIELDS}
    if subset.get("received_at") is not None:
        subset["received_at"] = normalize_timestamp(str(subset["received_at"]))
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


def resolve_evidence_key() -> str:
    """
    Kanıt imzalama anahtarını çözer (TS `resolveEvidenceKey` ile aynı sözleşme):
      - MIRAGE_EVIDENCE_HMAC_KEY varsa onu kullanır.
      - Yerel dry-run'da (production değil ve MIRAGE_EDGE_DRY_RUN açık) sabit
        yerel anahtar döner.
      - Aksi halde "" döner → çağıran fail-closed davranmalıdır.
    """
    import os

    key = (os.environ.get("MIRAGE_EVIDENCE_HMAC_KEY") or "").strip()
    if key:
        return key
    production = (os.environ.get("MIRAGE_ENV") or "").lower() == "production"
    dry = (os.environ.get("MIRAGE_EDGE_DRY_RUN") or "").strip().lower()
    dry_run = dry in ("1", "true", "yes", "on")
    if not production and dry_run:
        return "mirage-local-dry-run-evidence-key"
    return ""


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
