"""
MIRAGE — MCP gateway (politika uygulama + sunucu risk puanlama + denetim).

Ajanlar Model Context Protocol (MCP) sunucuları üzerinden araç çağırır. Bu
katman, çağrı **yapılmadan önce** üç karar üretir:

  1. **Politika** — sunucu/araç allow-deny, HTTPS zorunluluğu, azami risk.
  2. **Sunucu risk puanı** — beyan edilen yetenek/araçlardan deterministik skor
     (exec/fs/net/credential gibi tehlikeli yüzeyler yükseltir).
  3. **Denetim günlüğü** — her karar append-only kaydedilir (kim, ne, karar).

Tasarım (mevcut katmanlarla tutarlı):
  - Deterministik/senkron; LLM gerekmez.
  - Fail-closed: bilinmeyen/eksik bilgi muhafazakâr yorumlanır.
  - Kanıt/triyaj zincirinden bağımsız; isteğe bağlı olarak bir tarama kancası
    (`scan_hook`) ile ajan guard'ına bağlanabilir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .severity import SEVERITY_LEVELS as _RISK_LEVELS, SEVERITY_ORDER as _RISK_ORDER, level_for_score

# Araç adı ipuçları → risk ağırlığı ve gerekçe.
# Sıra ÖNEMLİ: daha spesifik/yüksek-riskli kalıplar önce denenir (ilk eşleşme
# kazanır), böylece ör. "get_credentials" içindeki "ls" yanlışlıkla "dosya
# okuma" sayılmaz.
_TOOL_RISK_HINTS: tuple[tuple[re.Pattern[str], int, str], ...] = (
    (re.compile(r"(exec|shell|command|run|eval|spawn|system)", re.I), 40,
     "kod/kabuk yürütme aracı"),
    (re.compile(r"(credential|secret|token|key|password|auth)", re.I), 35,
     "kimlik bilgisi erişim aracı"),
    (re.compile(r"(payment|transfer|invoice|billing)", re.I), 35,
     "finansal işlem aracı"),
    (re.compile(r"(write|delete|remove|unlink|move|chmod|chown|\brm\b)", re.I), 30,
     "yıkıcı dosya işlemi aracı"),
    (re.compile(r"(http|fetch|request|curl|download|upload|browser|url)", re.I), 25,
     "ağ erişim aracı"),
    (re.compile(r"(sql|query|database|mongo|postgres|\bdb\b)", re.I), 20,
     "veritabanı erişim aracı"),
    (re.compile(r"(email|smtp|send|message|sms|slack|webhook)", re.I), 20,
     "dış mesaj gönderme aracı"),
    (re.compile(r"(read|cat|list|glob|find|open)", re.I), 10,
     "dosya okuma aracı"),
)

# Yetenek bayrakları → risk ağırlığı.
_CAPABILITY_RISK: dict[str, tuple[int, str]] = {
    "filesystem": (20, "dosya sistemi erişimi"),
    "exec": (40, "kod yürütme"),
    "network": (20, "ağ erişimi"),
    "database": (20, "veritabanı erişimi"),
    "credentials": (35, "kimlik bilgisi erişimi"),
    "sampling": (15, "LLM sampling (istemciye geri çağrı)"),
}


@dataclass(frozen=True)
class MCPServerInfo:
    name: str
    url: str = ""
    transport: str = "stdio"  # "stdio" | "http" | "sse"
    capabilities: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    authenticated: bool = False


@dataclass(frozen=True)
class MCPServerRisk:
    score: int  # 0..100
    level: str  # low | medium | high | critical
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MCPPolicy:
    allowed_servers: tuple[str, ...] = ()
    denied_servers: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    denied_tools: tuple[str, ...] = ()
    max_risk_level: str = "critical"
    require_https: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GatewayDecision:
    allowed: bool
    reason: str
    server: str
    tool: str
    risk: MCPServerRisk

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "server": self.server,
            "tool": self.tool,
            "risk": self.risk.to_dict(),
        }




def score_server(server: MCPServerInfo) -> MCPServerRisk:
    """
    Bir MCP sunucusunu deterministik olarak puanlar (0..100).

    Ağırlıklar toplanır ve 100'de sınırlanır; her katkı bir gerekçe üretir.
    """
    score = 0
    reasons: list[str] = []

    for cap in server.capabilities:
        weight, reason = _CAPABILITY_RISK.get(cap.strip().lower(), (0, ""))
        if weight:
            score += weight
            reasons.append(f"yetenek: {reason}")

    seen: set[str] = set()
    for tool in server.tools:
        for pattern, weight, reason in _TOOL_RISK_HINTS:
            if pattern.search(tool) and reason not in seen:
                score += weight
                reasons.append(f"araç '{tool}': {reason}")
                seen.add(reason)
                break

    if server.transport == "http" and not server.authenticated:
        score += 20
        reasons.append("kimlik doğrulamasız HTTP taşıma")
    if server.transport == "http" and server.url.startswith("http://"):
        score += 15
        reasons.append("şifresiz (http://) taşıma")

    score = min(score, 100)
    return MCPServerRisk(score=score, level=level_for_score(score), reasons=reasons)


class MCPGateway:
    """
    MCP çağrıları için politika + risk + denetim kapısı.

    Args:
        policy: uygulanacak `MCPPolicy`.
        scan_hook: opsiyonel `(text) -> None`; çağrı argümanları için ek tarama
            (ör. `AgentGuard.guard_mcp_message` sarmalayıcısı). İhlalde
            exception yükseltirse karar `allowed=False` olur.
    """

    def __init__(
        self,
        *,
        policy: Optional[MCPPolicy] = None,
        scan_hook: Optional[Callable[[str], None]] = None,
        audit_sink: Optional[Callable[[dict[str, Any]], None]] = None,
    ):
        self.policy = policy or MCPPolicy()
        self.scan_hook = scan_hook
        self.audit_log: list[dict[str, Any]] = []
        # Opsiyonel kalıcı denetim yazıcısı (ör. `MCPAuditStore.save`).
        # `audit_log` bellekte tutulduğu için restart'ta sıfırlanır; ürün
        # "append-only, değiştirilemez kayıt" dediği için kalıcı denetim
        # gerekir. Sink verilmezse davranış tam olarak eskisi gibi kalır.
        self.audit_sink = audit_sink

    def evaluate(
        self,
        server: MCPServerInfo,
        tool: str,
        *,
        arguments: Any = None,
        actor: str = "",
    ) -> GatewayDecision:
        """Bir MCP araç çağrısını değerlendirir ve denetim günlüğüne yazar."""
        risk = score_server(server)
        decision = self._decide(server, tool, arguments, risk)
        self._audit(server, tool, decision, actor)
        return decision

    def _decide(
        self,
        server: MCPServerInfo,
        tool: str,
        arguments: Any,
        risk: MCPServerRisk,
    ) -> GatewayDecision:
        p = self.policy
        name = server.name

        def deny(reason: str) -> GatewayDecision:
            return GatewayDecision(False, reason, name, tool, risk)

        if name in p.denied_servers:
            return deny("sunucu deny-listesinde")
        if p.allowed_servers and name not in p.allowed_servers:
            return deny("sunucu allow-listesinde değil")
        if tool in p.denied_tools:
            return deny("araç deny-listesinde")
        if p.allowed_tools and tool not in p.allowed_tools:
            return deny("araç allow-listesinde değil")
        if p.require_https and server.transport == "http" and not server.url.startswith("https://"):
            return deny("HTTPS zorunlu ancak sunucu https değil")
        if _RISK_ORDER[risk.level] > _RISK_ORDER.get(p.max_risk_level, 4):
            return deny(f"sunucu riski {risk.level} > azami {p.max_risk_level}")

        if self.scan_hook is not None:
            try:
                self.scan_hook(_stringify(arguments))
            except Exception as err:  # fail-closed: tarama patlarsa çağrı yapılmaz
                return deny(f"tarama kancası engelledi: {type(err).__name__}")

        return GatewayDecision(True, "izinli", name, tool, risk)

    def _audit(
        self,
        server: MCPServerInfo,
        tool: str,
        decision: GatewayDecision,
        actor: str,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "server": server.name,
            "tool": tool,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "risk_score": decision.risk.score,
            "risk_level": decision.risk.level,
        }
        self.audit_log.append(entry)

        # Kalıcı denetim (varsa). Yazma hatası kararı DEĞİŞTİRMEZ:
        # gateway'in görevi çağrıyı engellemek/izin vermek, denetim
        # yazımı ise kanıt üretmek. İkisi birbirine bağımlı olmamalı —
        # aksi halde bir veritabanı kesintisi tüm MCP trafiğini düşürürdü.
        if self.audit_sink is not None:
            try:
                self.audit_sink(entry)
            except Exception:
                # Denetim yazımı başarısız olursa karar yine de geçerlidir;
                # sessizce yutulur çünkü burası karar noktası değil.
                pass

    def audit_summary(self) -> dict[str, Any]:
        """Denetim günlüğü özeti (toplam/izinli/engelli + risk dağılımı)."""
        by_level: dict[str, int] = {}
        for entry in self.audit_log:
            by_level[entry["risk_level"]] = by_level.get(entry["risk_level"], 0) + 1
        allowed = sum(1 for e in self.audit_log if e["allowed"])
        return {
            "total": len(self.audit_log),
            "allowed": allowed,
            "denied": len(self.audit_log) - allowed,
            "by_risk_level": by_level,
        }


def _stringify(value: Any) -> str:
    import json

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def default_policy_from_env() -> MCPPolicy:
    """
    `MIRAGE_MCP_*` env'inden politika üretir.

    - `MIRAGE_MCP_ALLOW_SERVERS` / `MIRAGE_MCP_DENY_SERVERS` (virgülle)
    - `MIRAGE_MCP_ALLOW_TOOLS` / `MIRAGE_MCP_DENY_TOOLS`
    - `MIRAGE_MCP_MAX_RISK` (low|medium|high|critical, varsayılan critical)
    - `MIRAGE_MCP_REQUIRE_HTTPS` (truthy)
    """
    import os

    def _list(name: str) -> tuple[str, ...]:
        return tuple(x.strip() for x in os.environ.get(name, "").split(",") if x.strip())

    max_risk = os.environ.get("MIRAGE_MCP_MAX_RISK", "critical").strip().lower()
    if max_risk not in _RISK_ORDER:
        max_risk = "critical"
    return MCPPolicy(
        allowed_servers=_list("MIRAGE_MCP_ALLOW_SERVERS"),
        denied_servers=_list("MIRAGE_MCP_DENY_SERVERS"),
        allowed_tools=_list("MIRAGE_MCP_ALLOW_TOOLS"),
        denied_tools=_list("MIRAGE_MCP_DENY_TOOLS"),
        max_risk_level=max_risk,
        require_https=os.environ.get("MIRAGE_MCP_REQUIRE_HTTPS", "").strip().lower()
        in {"1", "true", "yes", "on"},
    )


__all__ = [
    "GatewayDecision",
    "MCPGateway",
    "MCPPolicy",
    "MCPServerInfo",
    "MCPServerRisk",
    "default_policy_from_env",
    "score_server",
]
