"""
MIRAGE — Zehirli RAG / veri kaynağı guard'ı.

Bir ajanın **bağlamına alınmadan önce** getirilen (retrieval) dokümanı tarar ve
karar verir: `allow` | `quarantine` | `reject`. Böylece RAG zehirlenmesi /
dolaylı prompt injection (IDPI) bağlama sızmadan kesilir.

Tasarım (mevcut katmanlarla tutarlı):
  - Tarama **tek kaynak**: `redteam.scan_text` (injection/jailbreak/sızdırma/
    gizli-Unicode/canary) yeniden kullanılır (DRY).
  - Deterministik/senkron; LLM gerekmez.
  - Gizli Unicode her durumda temizlenir (allow dahil) — görünmez taşıyıcı
    karakterler bağlama hiç girmez.
  - Fail-closed: şiddet eşiği aşılırsa varsayılan karar **engellemek**tir.

Env:
  MIRAGE_RAG_BLOCK       → reddet eşiği (varsayılan critical).
  MIRAGE_RAG_QUARANTINE  → karantina eşiği (varsayılan high).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from .redteam import Rule, max_severity, scan_text, _HIDDEN_UNICODE, _SEVERITY_ORDER

_ACTIONS = ("allow", "quarantine", "reject")


@dataclass(frozen=True)
class SourceDoc:
    """Bağlama alınmak istenen getirilmiş doküman."""

    source_id: str
    text: str
    origin: str = ""
    trust: str = "untrusted"  # "trusted" | "untrusted"


@dataclass(frozen=True)
class RAGVerdict:
    source_id: str
    action: str  # allow | quarantine | reject
    allowed: bool
    severity: Optional[str]
    findings: list[dict[str, Any]]
    sanitized_text: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "action": self.action,
            "allowed": self.allowed,
            "severity": self.severity,
            "findings": self.findings,
            "reasons": self.reasons,
        }


def strip_hidden_unicode(text: str) -> tuple[str, list[str]]:
    """Gizli Unicode (bidi/zero-width) karakterlerini temizler.

    Döndürür: `(temiz_metin, çıkarılan_karakter_adları)`.
    """
    removed: list[str] = []
    out_chars: list[str] = []
    for ch in text or "":
        name = _HIDDEN_UNICODE.get(ch)
        if name is not None:
            removed.append(name)
            continue
        out_chars.append(ch)
    return "".join(out_chars), removed


class RAGGuard:
    """
    Getirilen dokümanları bağlama almadan önce denetler.

    Args:
        block_threshold: bu şiddet ve üzeri → `reject` (varsayılan critical).
        quarantine_threshold: bu şiddet ve üzeri → `quarantine` (varsayılan high).
        rules: özel kurallar (varsayılan `redteam.DEFAULT_RULES`).
        quarantine_sink: opsiyonel `(doc, verdict) -> None`; karantina/red
            kararında çağrılır (ör. inceleme defterine yaz).
    """

    def __init__(
        self,
        *,
        block_threshold: str = "critical",
        quarantine_threshold: str = "high",
        rules: Optional[Iterable[Rule]] = None,
        quarantine_sink: Optional[Callable[[SourceDoc, RAGVerdict], None]] = None,
    ):
        self.block_threshold = block_threshold
        self.quarantine_threshold = quarantine_threshold
        self.rules = tuple(rules) if rules is not None else None
        self.quarantine_sink = quarantine_sink

    def inspect(self, doc: SourceDoc) -> RAGVerdict:
        """Bir dokümanı tarar, temizler ve karar üretir."""
        findings = scan_text(doc.text, rules=self.rules)
        severity = max_severity(findings)
        sanitized, removed = strip_hidden_unicode(doc.text)

        reasons: list[str] = []
        if removed:
            reasons.append(f"gizli Unicode temizlendi: {len(removed)} karakter")

        action = "allow"
        if severity is not None and _at_least(severity, self.block_threshold):
            action = "reject"
        elif severity is not None and _at_least(severity, self.quarantine_threshold):
            action = "quarantine"

        if action == "reject":
            reasons.append(f"şiddet {severity} ≥ blok eşiği {self.block_threshold}")
        elif action == "quarantine":
            reasons.append(f"şiddet {severity} ≥ karantina eşiği {self.quarantine_threshold}")

        verdict = RAGVerdict(
            source_id=doc.source_id,
            action=action,
            allowed=(action == "allow"),
            severity=severity,
            findings=findings,
            sanitized_text=sanitized if action != "reject" else "",
            reasons=reasons,
        )
        if action != "allow":
            self._notify(doc, verdict)
        return verdict

    def inspect_many(self, docs: Iterable[SourceDoc]) -> list[RAGVerdict]:
        return [self.inspect(doc) for doc in docs]

    def _notify(self, doc: SourceDoc, verdict: RAGVerdict) -> None:
        if self.quarantine_sink is None:
            return
        try:
            self.quarantine_sink(doc, verdict)
        except Exception:  # yakalama yolu asla karar yolunu bozmaz
            import logging

            logging.getLogger("mirage.rag_guard").warning(
                "rag quarantine sink failed", exc_info=True
            )


def _at_least(severity: str, threshold: str) -> bool:
    return _SEVERITY_ORDER.get(severity, 0) >= _SEVERITY_ORDER.get(threshold, 99)


def rag_policy_from_env() -> dict[str, str]:
    """`MIRAGE_RAG_BLOCK` / `MIRAGE_RAG_QUARANTINE` eşiklerini okur."""
    import os

    block = os.environ.get("MIRAGE_RAG_BLOCK", "critical").strip().lower()
    quarantine = os.environ.get("MIRAGE_RAG_QUARANTINE", "high").strip().lower()
    if block not in _SEVERITY_ORDER:
        block = "critical"
    if quarantine not in _SEVERITY_ORDER:
        quarantine = "high"
    return {"block_threshold": block, "quarantine_threshold": quarantine}


def summarize(verdicts: Iterable[RAGVerdict]) -> dict[str, Any]:
    """Karar listesi özeti (aksiyon dağılımı + şiddet dağılımı)."""
    items = list(verdicts)
    by_action = {a: 0 for a in _ACTIONS}
    by_severity: dict[str, int] = {}
    for v in items:
        by_action[v.action] = by_action.get(v.action, 0) + 1
        if v.severity:
            by_severity[v.severity] = by_severity.get(v.severity, 0) + 1
    return {
        "total": len(items),
        "by_action": by_action,
        "by_severity": by_severity,
        "blocked": by_action.get("quarantine", 0) + by_action.get("reject", 0),
    }


__all__ = [
    "RAGGuard",
    "RAGVerdict",
    "SourceDoc",
    "rag_policy_from_env",
    "strip_hidden_unicode",
    "summarize",
]
