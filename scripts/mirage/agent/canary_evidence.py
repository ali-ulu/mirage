"""
MIRAGE — Canary sızıntısını kanıt zincirine bağlama.

Bir canary sızıntısı, ilişkili honeytoken'ın `triggered_beacons` kanıt
zincirine bağlanır: zincir başının `chain_seq`'i ve zincirin doğrulama sonucu
(`verify_chain`) alınır. Böylece sızıntı triyajı, "hangi kanıt halkasına ait"
bilgisiyle birlikte append-only deftere yazılabilir.

Kanıt zincirinin kendisine **yazılmaz**: zincir edge function'a aittir ve
kripto bütünlüğü vardır (bkz. 0003/0004 tasarımı). Burada yalnızca bağ
çözülür; bağ çözülemezse fail-safe olarak `linked=False` döner ve triyaj
yine de üretilebilir (kanıt bağı opsiyonel zenginleştirmedir).
"""
from __future__ import annotations

from typing import Any, Optional

from ..supabase_registry import SupabaseOperationError


def resolve_chain_binding(store: Optional[Any], token: Optional[str]) -> dict[str, Any]:
    """
    Bir token'ı kanıt zincirine bağlar.

    Args:
        store: `EvidenceChainStore` örneği; None ise kanıt katmanı yok sayılır.
        token: honeytoken UUID'si; None/boş ise bağ kurulmaz.

    Returns:
        {"linked": bool, "chain_seq": Optional[int],
         "chain_verified": Optional[bool], "reason": Optional[str]}

        - `linked`: kanıt zincirinde bu token için en az bir kayıt var mı?
        - `chain_seq`: zincir başının (en yüksek) sırası.
        - `chain_verified`: zincirin doğrulama sonucu (anahtar yoksa None).
        - `reason`: bağ kurulamadıysa gerekçe (aksi halde None).
    """
    if not token:
        return {"linked": False, "chain_seq": None, "chain_verified": None, "reason": "no token provided"}
    if store is None:
        return {"linked": False, "chain_seq": None, "chain_verified": None, "reason": "evidence store unavailable"}

    try:
        records = store.list_chain(token)
    except SupabaseOperationError:
        return {"linked": False, "chain_seq": None, "chain_verified": None, "reason": "evidence store unavailable"}

    if not records:
        return {"linked": False, "chain_seq": None, "chain_verified": None, "reason": "no evidence records for token"}

    head = max(records, key=lambda r: int(r["chain_seq"]))
    chain_seq = int(head["chain_seq"])

    try:
        verification = store.verify(token)
    except SupabaseOperationError:
        return {"linked": True, "chain_seq": chain_seq, "chain_verified": None, "reason": "evidence store unavailable"}

    return {
        "linked": True,
        "chain_seq": chain_seq,
        "chain_verified": bool(verification.get("ok")),
        "reason": verification.get("reason"),
    }
