"""
MIRAGE — Şiddet seviyesi tek kaynağı.

`low | medium | high | critical` sıralaması ve 0..100 skoru seviyeye çeviren
eşikler daha önce `redteam`, `behavior`, `dlp`, `rag_guard` ve `mcp_gateway`
modüllerinde kopyalanmıştı. Tek tanım burada tutulur; yeni bir katman
seviye karşılaştıracaksa buradan import eder (sıralama kayması olmaz).
"""
from __future__ import annotations

SEVERITY_ORDER: dict[str, int] = {"low": 1, "medium": 2, "high": 3, "critical": 4}
SEVERITY_LEVELS: tuple[str, ...] = ("low", "medium", "high", "critical")

# Skor → seviye eşikleri (mcp_gateway risk puanı ve behavior niyet skoru ortak).
_LEVEL_THRESHOLDS: tuple[tuple[int, str], ...] = (
    (80, "critical"),
    (55, "high"),
    (30, "medium"),
)


def level_for_score(score: int) -> str:
    """0..100 skoru `low|medium|high|critical` seviyesine çevirir."""
    for threshold, level in _LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return "low"


def exceeds(severity: str, threshold: str) -> bool:
    """`severity` eşiğe eşit veya üstündeyse True (bilinmeyen eşik → en katı)."""
    return SEVERITY_ORDER.get(severity, 0) >= SEVERITY_ORDER.get(threshold, 99)


__all__ = [
    "SEVERITY_ORDER",
    "SEVERITY_LEVELS",
    "level_for_score",
    "exceeds",
]
