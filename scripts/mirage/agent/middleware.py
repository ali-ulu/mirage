"""
MIRAGE — Otomatik tarama middleware'i (ASGI).

`/agent/scan`'i manuel çağrıdan otomatik runtime korumasına taşır: ajan/LLM
yanıtları gibi JSON gövdeleri döndüren uçların **yanıt gövdesi** her istekte
taranır. Kayıtlı bir prompt-canary işareti sızarsa yanıt loglanır ve (istenirse)
triyaj defterine yazılır.

Tasarım:
  - ASGI middleware (BaseHTTPMiddleware değil) — StreamingResponse'lara
    (ör. /honeytoken XLSX) dokunmadan gövdeyi yakalamak için response-start
    mesajları izlenir ve yalnızca `application/json` gövdeler taranır.
  - Tarama `evaluate_rules`/`CanaryRegistry.match` üzerinden **senkron** ve
    deterministiktir; async orkestrasyon (`scan_text_for_leaks`, LLM triyajı)
    `/agent/scan`'e bırakılır. Böylece middleware yanıt yolunda bloklamaz.
  - Hariç tutulan yollar: canary üreten/tarayan uçlar (`/agent/canary`,
    `/agent/scan`) — bunlar canary'yi kasıtlı taşır, kendi sızıntıları değildir.
  - Fail-safe: herhangi bir tarama hatası yanıtı BOZMAZ (loglanır, devam).
  - Opt-in: `MIRAGE_SCAN_MIDDLEWARE` truthy değilse middleware eklenmez
    (mevcut testler/yerel kullanım etkilenmez).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("mirage.middleware")

# Kendi canary'lerini taşıyan uçlar taranmaz.
DEFAULT_EXCLUDED_PREFIXES = ("/agent/canary", "/agent/scan")

_TRUTHY = {"1", "true", "yes", "on"}


def scan_middleware_enabled() -> bool:
    return os.environ.get("MIRAGE_SCAN_MIDDLEWARE", "").strip().lower() in _TRUTHY


def should_scan_path(
    path: str, excluded: tuple[str, ...] = DEFAULT_EXCLUDED_PREFIXES
) -> bool:
    return not any(path == p or path.startswith(p + "/") for p in excluded)


class AgentScanMiddleware:
    """
    ASGI middleware: JSON yanıt gövdelerini canary/regex sızıntısına karşı tarar.

    Args:
        app: sarılan ASGI uygulaması.
        registry: `match(text) -> list` sağlayan canary registry.
        rules: müşteri regex kuralları (dict listesi).
        triage_sink: opsiyonel; sızıntıda `(text, leak) -> None` çağrılır.
        max_scan_bytes: bu boyuttan büyük gövdeler taranmaz (DoS koruması).
        excluded_prefixes: taranmayacak yol önekleri.
    """

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        registry: Any = None,
        rules: Optional[list[dict[str, Any]]] = None,
        triage_sink: Optional[Callable[[str, dict[str, Any]], None]] = None,
        max_scan_bytes: int = 262_144,
        excluded_prefixes: tuple[str, ...] = DEFAULT_EXCLUDED_PREFIXES,
    ):
        self.app = app
        self.registry = registry
        self.rules = rules or []
        self.triage_sink = triage_sink
        self.max_scan_bytes = max_scan_bytes
        self.excluded_prefixes = excluded_prefixes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not should_scan_path(
            scope.get("path", ""), self.excluded_prefixes
        ):
            await self.app(scope, receive, send)
            return

        state: dict[str, Any] = {
            "content_type": "",
            "chunks": [],
            "size": 0,
            "too_large": False,
        }

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = {
                    k.decode().lower(): v.decode()
                    for k, v in message.get("headers", [])
                }
                state["content_type"] = headers.get("content-type", "")
            elif message["type"] == "http.response.body":
                if "application/json" in state["content_type"] and not state["too_large"]:
                    body = message.get("body", b"")
                    state["size"] += len(body)
                    if state["size"] > self.max_scan_bytes:
                        state["too_large"] = True
                        state["chunks"] = []
                    else:
                        state["chunks"].append(body)
            await send(message)

        await self.app(scope, receive, send_wrapper)
        self._inspect(state)

    def _inspect(self, state: dict[str, Any]) -> None:
        if state["too_large"] or not state["chunks"]:
            return
        try:
            text = b"".join(state["chunks"]).decode("utf-8", errors="replace")
            leaks = self.registry.match(text) if self.registry is not None else []
            findings = self._evaluate(text)
        except Exception:  # fail-safe: tarama yanıtı asla bozmaz
            logger.warning("agent scan middleware failed", exc_info=True)
            return

        if not leaks and not findings:
            return

        logger.warning(
            "MIRAGE agent scan: leak detected (canaries=%d, rule_findings=%d)",
            len(leaks),
            len(findings),
        )
        if self.triage_sink is not None:
            try:
                self.triage_sink(
                    text,
                    {
                        "count": len(leaks),
                        "canaries": [c.to_dict() for c in leaks],
                        "findings": findings,
                    },
                )
            except Exception:
                logger.warning("agent scan triage sink failed", exc_info=True)

    def _evaluate(self, text: str) -> list[dict[str, Any]]:
        from .runtime import evaluate_rules

        return evaluate_rules(text, self.rules)


def install_agent_scan_middleware(app, *, registry: Any = None, **kwargs) -> None:
    """
    FastAPI uygulamasına tarama middleware'ini ekler. `registry` verilmezse
    server'ın canary registry'si kullanılır (uygulama yolu service_role).

    Yalnızca `MIRAGE_SCAN_MIDDLEWARE` truthy olduğunda etkilidir.
    """
    if not scan_middleware_enabled():
        return
    from .. import server as _server

    if registry is None:
        registry = _server.get_canary_registry()
    app.add_middleware(AgentScanMiddleware, registry=registry, **kwargs)


__all__ = [
    "AgentScanMiddleware",
    "DEFAULT_EXCLUDED_PREFIXES",
    "install_agent_scan_middleware",
    "scan_middleware_enabled",
    "should_scan_path",
]
