"""
MIRAGE — Satır-içi ajan koruması (API/MCP çağrılarını savunma/engelleme/yakalama).

Middleware yalnızca **yanıt gövdesini** tarar ve bloklamaz. Bu modül, ajanın
dış dünyaya dokunduğu iki sınırda **isteği göndermeden** karar verir:

  1. API çağrıları — `guard_api_call(payload)`: ajanın bir HTTP/gövde isteğine
     koyduğu metni tarar. İhlalde `GuardBlocked` yükseltir → istek gönderilmez.
  2. MCP çağrıları — `guard_mcp_message(message)`: JSON-RPC mesajını (tools/call
     arguments, sampling prompt, resources/read yanıtı) özyinelemeli tarar.
     `enforce=True` ise ihlalli `tools/call` yerine JSON-RPC `error` üretir.

Tasarım (mevcut katmanlarla tutarlı):
  - `OutboundScanner`'i yeniden kullanır (tek kaynak, DRY) — canary + regex.
  - **Fail-closed**: tarama beklenmedik şekilde patlarsa (enforce modunda)
    metin gönderilmez; sızıntı riski veri kaybından ağırdır.
  - Deterministik/senkron; LLM gerekmez.
  - İhlal triyajlanıp (senkron heuristic) opsiyonel deftere yazılabilir —
    böylece "yakalama" da kanıt/triyaj zincirine bağlanır.

Env:
  MIRAGE_AGENT_GUARD=1        → `enforce` varsayılanı true (opt-in).
  MIRAGE_GUARD_PERSIST=1      → ihlaller triyaj defterine yazılır.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Optional

from .outbound import OutboundLeakError, OutboundScanner

logger = logging.getLogger("mirage.guard")

_TRUTHY = {"1", "true", "yes", "on"}

# MCP JSON-RPC mesajında taranacak metin taşıyan alanlar (nokta yolu).
MCP_SCAN_PATHS = (
    "params.arguments",
    "params.name",
    "params.prompt",
    "params.messages",
    "params.content",
    "params.uri",
    "result.content",
    "result.structuredContent",
)

# MCP başarısız araç çağrısı için JSON-RPC hata kodu (sunucu hatası).
MCP_ERROR_CODE = -32000


def guard_enabled() -> bool:
    return os.environ.get("MIRAGE_AGENT_GUARD", "").strip().lower() in _TRUTHY


def guard_persist_enabled() -> bool:
    return os.environ.get("MIRAGE_GUARD_PERSIST", "").strip().lower() in _TRUTHY


class GuardBlocked(OutboundLeakError):
    """Enforce modunda ihlal nedeniyle çağrı engellendiğinde yükseltilir."""

    def __init__(self, leak: dict[str, Any], *, surface: str):
        self.surface = surface
        self.leak = leak
        RuntimeError.__init__(
            self,
            f"agent guard blocked {surface} "
            f"(canaries={leak.get('count', 0)}, rule_hits={leak.get('rule_hits', 0)})",
        )


def _flatten(value: Any) -> str:
    """İç içe (dict/list/str) değeri taranabilir tek metne indirger."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _get_path(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


class AgentGuard:
    """
    API ve MCP sınırlarında satır-içi savunma.

    Args:
        scanner: taranacak `OutboundScanner` (registry + rules + block).
        enforce: True ise ihlalde bloklar; False ise yalnızca raporlar.
        triage_sink: opsiyonel `(text, leak) -> None`; ihlalde çağrılır.
    """

    def __init__(
        self,
        *,
        scanner: OutboundScanner,
        enforce: bool = True,
        triage_sink: Optional[Callable[[str, dict[str, Any]], None]] = None,
    ):
        self.scanner = scanner
        self.enforce = enforce
        self.triage_sink = triage_sink

    # -- ortak ---------------------------------------------------------------
    def _decide(self, text: str, surface: str) -> dict[str, Any]:
        """Metni tarar; enforce + ihlal ise GuardBlocked yükseltir."""
        if self.enforce:
            try:
                report = self.scanner.guard(text)  # ihlalde OutboundLeakError
            except OutboundLeakError as err:
                report = {
                    **err.leak,
                    "surface": surface,
                    "blocked": True,
                    "clean": False,
                }
                self._persist(text, report)
                raise GuardBlocked(report, surface=surface) from err
        else:
            report = self.scanner.scan(text)
        if not report.get("clean", True):
            report = {**report, "surface": surface, "blocked": self.enforce}
            self._persist(text, report)
            if self.enforce:
                raise GuardBlocked(report, surface=surface)
        return report

    def _persist(self, text: str, leak: dict[str, Any]) -> None:
        if self.triage_sink is None:
            return
        try:
            self.triage_sink(text, leak)
        except Exception:  # yakalama yolu asla engelleme kararını bozmaz
            logger.warning("agent guard triage sink failed", exc_info=True)

    # -- API sınırı ----------------------------------------------------------
    def guard_api_call(self, payload: Any, *, surface: str = "api-call") -> dict[str, Any]:
        """Ajanın dış API'ye gönderdiği gövdeyi tarar; ihlalde bloklar."""
        return self._decide(_flatten(payload), surface)

    # -- MCP sınırı ----------------------------------------------------------
    def guard_mcp_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """
        Bir MCP JSON-RPC mesajını tarar.

        `enforce` modunda ihlal varsa:
          - `id` taşıyan istek → ihlalli yanıt yerine JSON-RPC `error` döner
            (`{"jsonrpc":"2.0","id":...,"error":{"code":-32000,...}}`).
          - id'siz (bildirim) → `{"blocked": True, ...}` raporu.

        Her durumda `{"clean", "blocked", "leak", ...}` özeti döner.
        """
        text = self._collect_mcp_text(message)
        try:
            report = self._decide(text, "mcp")
        except GuardBlocked as err:
            report = err.leak
        blocked = self.enforce and not report.get("clean", True)
        out: dict[str, Any] = {
            "clean": report.get("clean", True),
            "blocked": blocked,
            "leak": report,
        }
        if blocked and "id" in message:
            out["response"] = {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {
                    "code": MCP_ERROR_CODE,
                    "message": "MIRAGE agent guard: leak blocked",
                    "data": {
                        "canaries": report.get("count", 0),
                        "rule_hits": report.get("rule_hits", 0),
                    },
                },
            }
        return out

    def _collect_mcp_text(self, message: dict[str, Any]) -> str:
        parts = [_flatten(_get_path(message, p)) for p in MCP_SCAN_PATHS]
        return "\n".join(p for p in parts if p)


def guard_paths() -> tuple[str, ...]:
    """Korunacak yol önekleri (`MIRAGE_GUARD_PATHS`, virgülle ayrılmış)."""
    raw = os.environ.get("MIRAGE_GUARD_PATHS", "/agent/proxy")
    return tuple(p.strip() for p in raw.split(",") if p.strip())


class AgentGuardMiddleware:
    """
    ASGI middleware: ajanın GİDEN API çağrısı gövdelerini (proxy uçları)
    uygulamaya ulaşmadan önce tarar; enforce modunda ihlalde **422** döner,
    istek upstream'e iletilmez.

    Yalnızca `MIRAGE_AGENT_GUARD` truthy olduğunda `install_...` ekler.
    """

    def __init__(
        self,
        app: Callable[..., Any],
        *,
        guard: AgentGuard,
        protect_prefixes: tuple[str, ...] = ("/agent/proxy",),
        max_body_bytes: int = 262_144,
    ):
        self.app = app
        self.guard = guard
        self.protect_prefixes = protect_prefixes
        self.max_body_bytes = max_body_bytes

    def _protected(self, path: str) -> bool:
        return any(
            path == p or path.startswith(p + "/") for p in self.protect_prefixes
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self._protected(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        body = b""
        while True:
            message = await receive()
            if message["type"] == "http.request":
                body += message.get("body", b"")
                if len(body) > self.max_body_bytes:
                    body = body[: self.max_body_bytes]
                    break
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                return

        text = body.decode("utf-8", errors="replace")
        try:
            self.guard.guard_api_call(text, surface="api-proxy")
        except GuardBlocked as blocked:
            await self._reject(scope, receive, send, blocked.leak)
            return

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay, send)

    async def _reject(self, scope, receive, send, leak: dict[str, Any]) -> None:
        from starlette.responses import JSONResponse

        response = JSONResponse(
            status_code=422,
            content={
                "detail": "MIRAGE agent guard: leak blocked",
                "canaries": leak.get("count", 0),
                "rule_hits": leak.get("rule_hits", 0),
                "findings": leak.get("findings", []),
            },
        )
        await response(scope, receive, send)


def install_agent_guard_middleware(app, **kwargs) -> None:
    """
    FastAPI uygulamasına satır-içi guard middleware'ini ekler.

    Yalnızca `MIRAGE_AGENT_GUARD` truthy olduğunda etkilidir. `guard` verilmezse
    `get_agent_guard()` ile kurulur; `protect_prefixes` verilmezse
    `MIRAGE_GUARD_PATHS` (varsayılan `/agent/proxy`) kullanılır.
    """
    if not guard_enabled():
        return
    guard = kwargs.pop("guard", None) or get_agent_guard()
    prefixes = kwargs.pop("protect_prefixes", None) or guard_paths()
    app.add_middleware(
        AgentGuardMiddleware, guard=guard, protect_prefixes=prefixes, **kwargs
    )


def build_guard_sink() -> Callable[[str, dict[str, Any]], None]:
    """İhlalleri senkron heuristic ile triyajlayıp deftere yazan varsayılan sink."""
    from .. import server as _server
    from .canary_triage import heuristic_canary_triage

    def _sink(text: str, leak: dict[str, Any]) -> None:
        canaries = leak.get("canaries") or []
        token = canaries[0].get("token") if canaries else None
        if not token:
            return
        result = heuristic_canary_triage(leak)
        try:
            store = _server.get_triage_store()
        except Exception:
            logger.info("agent guard sink: triage ledger not configured; skipping")
            return
        store.save(token, result, team_id=canaries[0].get("team_id"))

    return _sink


def get_agent_guard(
    *,
    registry: Any = None,
    rules: Optional[list[dict[str, Any]]] = None,
    enforce: Optional[bool] = None,
    persist: Optional[bool] = None,
) -> AgentGuard:
    """
    Yapılandırılmış bir `AgentGuard` döndürür.

    `registry` verilmezse server'ın canary registry'si kullanılır. `enforce`
    verilmezse `MIRAGE_AGENT_GUARD` env'ine, `persist` verilmezse
    `MIRAGE_GUARD_PERSIST` env'ine bakılır.
    """
    if registry is None:
        from .. import server as _server

        registry = _server.get_canary_registry()
    if enforce is None:
        enforce = guard_enabled()
    if persist is None:
        persist = guard_persist_enabled()

    scanner = OutboundScanner(registry=registry, rules=rules or [], block=enforce)
    sink = build_guard_sink() if persist else None
    return AgentGuard(scanner=scanner, enforce=enforce, triage_sink=sink)


__all__ = [
    "AgentGuard",
    "GuardBlocked",
    "MCP_ERROR_CODE",
    "MCP_SCAN_PATHS",
    "build_guard_sink",
    "get_agent_guard",
    "guard_enabled",
    "guard_persist_enabled",
]
