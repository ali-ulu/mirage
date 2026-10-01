"""
MIRAGE — Giden (upstream) sızıntı tarama çekirdeği.

Middleware yanıt GÖVDESİNİ tarar; bu modül ajan→LLM/araç çağrısı gibi GİDEN
metinleri tarar. Amaç: kayıtlı canary veya müşteri regex kuralı yakalanan
metnin upstream'e gitmesini (sızmasını) engellemek.

Tasarım:
  - `OutboundScanner` saf/senkron: `registry.match` + `evaluate_rules`.
  - İki mod: `block=True` → ihlalde `OutboundLeakError` yükseltir (çağıran
    isteği göndermeden durur); `block=False` → yalnızca raporlar.
  - Fail-safe değil, **fail-closed**: tarama sırasında beklenmeyen hata olursa
    (blok modunda) metin gönderilmez — sızıntı riski veri kaybından ağırdır.
  - Middleware ile aynı `evaluate_rules`'i kullanır (tek kaynak, DRY).
"""
from __future__ import annotations

from typing import Any, Optional

from .runtime import evaluate_rules


class OutboundLeakError(RuntimeError):
    """Blok modunda giden metin ihlal içerdiğinde yükseltilir."""

    def __init__(self, leak: dict[str, Any]):
        self.leak = leak
        super().__init__(
            f"outbound leak blocked (canaries={leak.get('count', 0)}, "
            f"rule_hits={leak.get('rule_hits', 0)})"
        )


class OutboundScanner:
    """
    Giden metni canary + regex kurallarına göre tarar.

    Args:
        registry: `match(text) -> list` sağlayan canary registry (opsiyonel).
        rules: müşteri regex kuralları.
        block: True ise ihlalde `OutboundLeakError` yükseltir.
    """

    def __init__(
        self,
        *,
        registry: Any = None,
        rules: Optional[list[dict[str, Any]]] = None,
        block: bool = False,
    ):
        self.registry = registry
        self.rules = rules or []
        self.block = block

    def scan(self, text: str) -> dict[str, Any]:
        """Metni tarar; ihlal raporunu döndürür (asla yükseltmez)."""
        canaries = self.registry.match(text) if self.registry is not None else []
        findings = evaluate_rules(text or "", self.rules)
        return {
            "leaked": bool(canaries),
            "count": len(canaries),
            "canaries": [c.to_dict() for c in canaries],
            "rule_hits": len(findings),
            "findings": findings,
            "clean": not canaries and not findings,
        }

    def guard(self, text: str) -> dict[str, Any]:
        """
        `scan` sonucunu döndürür; `block` modunda ihlalde `OutboundLeakError`
        yükseltir. Tarama beklenmedik şekilde patlarsa (blok modunda) fail-closed
        olarak yükseltir.
        """
        try:
            report = self.scan(text)
        except Exception:
            if self.block:
                raise OutboundLeakError(
                    {"count": 0, "rule_hits": 0, "reason": "scan_error", "clean": False}
                )
            raise
        if self.block and not report["clean"]:
            raise OutboundLeakError(report)
        return report


__all__ = ["OutboundLeakError", "OutboundScanner"]
