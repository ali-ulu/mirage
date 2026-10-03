"""
MIRAGE — MCP gateway denetim defteri (Supabase-backed).

Gateway'in verdiği her politika/risk kararını append-only `mcp_audit`
tablosuna yazar ve okur.

Neden tablo gerekli:
  - `MCPGateway.audit_log` bellekte tutulan bir liste olup SÜREÇ ÖMRÜNE
    bağlıdır; restart'ta sıfırlanır. Ürün "append-only, değiştirilemez
    kayıt" dediği için bir denetim kaydının kaybolması kabul edilemez.
  - Dashboard MCP paneli kalıcı kayıttan okur. Bellekten okusa her
    deploy'da boş ekran gösterecek ve "koruma yok" izlenimi üretirdi.

Tasarım (diğer store'larla tutarlı):
  - Yalnızca INSERT ve okuma yapar; DB trigger'ı UPDATE/DELETE'i yasaklar.
  - Yazma hatası karar noktasını ETKİLEMEZ: gateway çağrıyı
    engellemek/izin vermek için, store yalnızca kanıt üretmek içindir.
    Aksi halde bir veritabanı kesintisi tüm MCP trafiğini düşürürdü.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional

from .supabase_registry import (
    SupabaseClient,
    SupabaseOperationError,
    _safe_supabase_call,
    build_supabase_client_from_env,
)


@dataclass(frozen=True)
class MCPAuditRecord:
    """Kalıcı denetim kaydı (DB satırının Python karşılığı)."""

    server: str
    tool: str
    allowed: bool
    reason: str = ""
    risk_score: float = 0
    risk_level: str = "low"
    actor: str = ""
    occurred_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MCPAuditStore:
    """`mcp_audit` tablosu için INSERT + okuma."""

    TABLE_NAME = "mcp_audit"

    def __init__(self, client: Optional[SupabaseClient] = None):
        self._client = client if client is not None else build_supabase_client_from_env()

    @staticmethod
    def as_sink() -> "MCPAuditStore":
        """`MCPGateway(audit_sink=...)` için bağlanabilir yazıcı."""
        return MCPAuditStore()

    def save(self, record: MCPAuditRecord) -> dict[str, Any]:
        """Denetim kaydını yazar. Hata durumunda `SupabaseOperationError`."""
        payload = record.to_dict()
        payload.pop("occurred_at", None)  # DB varsayılanı kullanır

        def _do_insert():
            return (
                self._client.table(self.TABLE_NAME)
                .insert(payload)
                .execute()
            )

        result = _safe_supabase_call("mcp_audit_insert", _do_insert)
        if not result or not result.data:
            raise SupabaseOperationError("mcp_audit insert returned no data")
        return dict(result.data[0])

    def save_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """`MCPGateway._audit` çıktısından doğrudan kaydet."""
        return self.save(
            MCPAuditRecord(
                server=str(entry.get("server", "")),
                tool=str(entry.get("tool", "")),
                allowed=bool(entry.get("allowed", False)),
                reason=str(entry.get("reason", "")),
                risk_score=float(entry.get("risk_score", 0) or 0),
                risk_level=str(entry.get("risk_level", "low")),
                actor=str(entry.get("actor", "")),
            )
        )

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Son denetim kayıtlarını yeni->eski sırada döndürür."""
        def _do_list():
            return (
                self._client.table(self.TABLE_NAME)
                .select("id, occurred_at, actor, server, tool, allowed, reason, risk_score, risk_level")
                .order("occurred_at", desc=True)
                .limit(limit)
                .execute()
            )

        result = _safe_supabase_call("mcp_audit_list", _do_list)
        if not result or not result.data:
            return []
        return [dict(row) for row in result.data]

    def summary(self) -> dict[str, Any]:
        """Toplam/izinli/engelli + risk seviyesi dağılımı."""
        rows = self.list_recent(limit=1000)
        by_level: dict[str, int] = {}
        for row in rows:
            level = str(row.get("risk_level", "low"))
            by_level[level] = by_level.get(level, 0) + 1
        allowed = sum(1 for r in rows if r.get("allowed"))
        return {
            "total": len(rows),
            "allowed": allowed,
            "denied": len(rows) - allowed,
            "by_risk_level": by_level,
        }