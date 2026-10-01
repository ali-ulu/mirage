"""
MIRAGE — Kanıt zinciri okuma + doğrulama deposu (Supabase-backed).

`triggered_beacons` tablosundaki kanıt kayıtlarını okur ve Python kanıt
çekirdeği (`mirage.evidence.verify_chain`) ile doğrular. Edge function'ın
yazdığı zinciri **bağımsız** olarak yeniden hesaplar; böylece kanıtın
kurcalanmadığı DB dışında da gösterilebilir.

Not: `received_at`, Postgres `timestamptz`'ten okunurken biçim değiştirir
(`...000Z` -> `...+00:00`). `evidence.normalize_timestamp` bu farkı yutar;
bu yüzden DB'den okunan kayıtlar da doğru hash üretir.
"""
from __future__ import annotations

from typing import Any, Optional

from .evidence import resolve_evidence_key, verify_chain
from .supabase_registry import (
    SupabaseClient,
    SupabaseNotConfiguredError,
    SupabaseOperationError,
    _safe_supabase_call,
    build_supabase_client_from_env,
)

# Kanıt kaydının kanonik alanları (id/opener_app gibi türev alanlar hariç).
_EVIDENCE_COLUMNS = "token, ip, user_agent, received_at, chain_seq, prev_hash, record_hash, hmac"


class EvidenceChainStore:
    """`triggered_beacons` kanıt zinciri için okuma/doğrulama deposu."""

    TABLE_NAME = "triggered_beacons"

    def __init__(self, client: Optional[SupabaseClient] = None):
        if client is not None:
            self._client = client
        else:
            self._client = build_supabase_client_from_env()

    def list_chain(self, token: str) -> list[dict[str, Any]]:
        """Bir token'a ait kanıt kayıtlarını chain_seq sırasıyla döndürür."""
        def _do_list():
            return (
                self._client.table(self.TABLE_NAME)
                .select(_EVIDENCE_COLUMNS)
                .eq("token", token)
                .order("chain_seq", desc=False)
                .execute()
            )

        result = _safe_supabase_call("list_evidence_chain", _do_list)
        if not result or not result.data:
            return []
        return list(result.data)

    def verify(self, token: str, key: Optional[str] = None) -> dict[str, Any]:
        """
        Bir token'ın zincirini doğrular. Anahtar verilmezse `resolve_evidence_key()`
        kullanılır; anahtar yoksa fail-closed (ok=False, reason='signing key
        unavailable').

        Döndürür: {"ok", "checked", "broken_at", "reason"} + "token".
        """
        records = self.list_chain(token)
        resolved = key if key is not None else resolve_evidence_key()
        if not resolved:
            return {
                "token": token,
                "ok": False,
                "checked": 0,
                "broken_at": None,
                "reason": "signing key unavailable",
            }
        result = verify_chain(records, resolved)
        return {"token": token, **result}
