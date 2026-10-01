"""
MIRAGE — Beacon triyaj kayıt defteri (Supabase-backed).

Kanıt zincirine (triggered_beacons) bağlı bir triyaj değerlendirmesini
append-only `beacon_triage` tablosuna yazar ve okur. Triyaj LLM veya
deterministik sezgisel (heuristic) ile üretilebilir; `source` alanı hangisi
olduğunu açıkça taşır.

Tasarım:
  - Kanıt zinciri (0003) edge function'a aittir ve kripto bütünlüğü vardır.
    Triyaj ayrı bir defterde tutulur; kanıt zincirine dokunmaz. Triyaj
    yeniden çalıştırılsa bile kanıt değişmez.
  - Depo yalnızca INSERT ve okuma yapar; DB trigger'ı UPDATE/DELETE'i yasaklar.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional

from .llm.triage import VALID_ACTIONS, VALID_SEVERITIES, TriageResult
from .supabase_registry import (
    SupabaseClient,
    SupabaseOperationError,
    _safe_supabase_call,
    build_supabase_client_from_env,
)


@dataclass(frozen=True)
class TriageRecord:
    """Kalıcı triyaj kaydı (DB satırının Python karşılığı)."""

    token: str
    severity: str
    confidence: float
    rationale: str
    recommended_action: str
    source: str
    chain_seq: Optional[int] = None
    chain_verified: Optional[bool] = None
    model: Optional[str] = None
    created_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate(severity: str, action: str, confidence: float) -> None:
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"invalid severity: {severity!r}")
    if action not in VALID_ACTIONS:
        raise ValueError(f"invalid recommended_action: {action!r}")
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence out of range: {confidence!r}")


class BeaconTriageStore:
    """`beacon_triage` tablosu için append-only depo."""

    TABLE_NAME = "beacon_triage"

    def __init__(self, client: Optional[SupabaseClient] = None):
        if client is not None:
            self._client = client
        else:
            self._client = build_supabase_client_from_env()

    def save(
        self,
        token: str,
        result: TriageResult,
        *,
        chain_seq: Optional[int] = None,
        model: Optional[str] = None,
    ) -> TriageRecord:
        """Bir triyaj sonucunu kalıcı kayda dönüştürüp yazar."""
        _validate(result.severity, result.recommended_action, result.confidence)

        record = TriageRecord(
            token=token,
            severity=result.severity,
            confidence=float(result.confidence),
            rationale=result.rationale,
            recommended_action=result.recommended_action,
            source=result.source,
            chain_seq=chain_seq,
            chain_verified=result.chain_verified,
            model=model,
        )
        payload = {
            "token": token,
            "chain_seq": chain_seq,
            "severity": record.severity,
            "confidence": record.confidence,
            "rationale": record.rationale,
            "recommended_action": record.recommended_action,
            "source": record.source,
            "chain_verified": record.chain_verified,
            "model": record.model,
        }

        def _do_insert():
            return self._client.table(self.TABLE_NAME).insert(payload).execute()

        _safe_supabase_call("insert_beacon_triage", _do_insert)
        return record

    def list_for_token(self, token: str, limit: int = 50) -> list[TriageRecord]:
        """Bir token için triyaj kayıtlarını (en yeni önce) döndürür."""
        def _do_list():
            return (
                self._client.table(self.TABLE_NAME)
                .select("*")
                .eq("token", token)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )

        try:
            result = _safe_supabase_call("list_beacon_triage", _do_list)
        except SupabaseOperationError:
            return []

        if not result or not result.data:
            return []

        return [self._row_to_record(row) for row in result.data]

    @staticmethod
    def _row_to_record(row: dict) -> TriageRecord:
        return TriageRecord(
            token=str(row.get("token", "")),
            severity=str(row.get("severity", "")),
            confidence=float(row.get("confidence", 0.0)),
            rationale=str(row.get("rationale", "")),
            recommended_action=str(row.get("recommended_action", "")),
            source=str(row.get("source", "")),
            chain_seq=(int(row["chain_seq"]) if row.get("chain_seq") is not None else None),
            chain_verified=row.get("chain_verified"),
            model=row.get("model"),
            created_at=(str(row["created_at"]) if row.get("created_at") is not None else None),
        )
