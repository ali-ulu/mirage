"""
MIRAGE — Ajan davranış analitiği (saldırgan niyeti skorlama).

Rakiplerin "davranış analitiği" iddiasına karşılık: triyaj defterindeki
olayları (canary sızıntıları, beacon yoklamaları) **sinyal imzalarına** göre
deterministik biçimde skorlar ve bir saldırgan niyeti profili üretir.

Tasarım (mevcut katmanlarla tutarlı):
  - Girdi olarak `TriageRecord`/`TriageResult` benzeri düz sözlükler alır;
    store'a bağımlı değildir (tek sorumluluk).
  - Deterministik/senkron; LLM gerekmez.
  - Fail-safe: tanınmayan alanlar yok sayılır, bozuk kayıt akışı bozmaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

_SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass(frozen=True)
class BehaviorSignal:
    name: str
    weight: int
    detail: str


@dataclass(frozen=True)
class BehaviorProfile:
    intent_score: int  # 0..100
    intent_level: str  # low | medium | high | critical
    sophistication: str  # opportunistic | targeted | advanced
    signals: list[BehaviorSignal]
    event_count: int
    recommended_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_score": self.intent_score,
            "intent_level": self.intent_level,
            "sophistication": self.sophistication,
            "signals": [{"name": s.name, "weight": s.weight, "detail": s.detail}
                        for s in self.signals],
            "event_count": self.event_count,
            "recommended_action": self.recommended_action,
        }


def _intent_level(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def _action_for(level: str) -> str:
    return {
        "critical": "escalate",
        "high": "investigate",
        "medium": "monitor",
        "low": "ignore",
    }[level]


def _get(event: Any, key: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default)


def analyze(
    events: Iterable[Any],
    *,
    distinct_actors: Optional[int] = None,
) -> BehaviorProfile:
    """
    Olay dizisini analiz eder ve saldırgan niyeti profilini döndürür.

    Args:
        events: `TriageRecord`/`TriageResult` benzeri nesneler ya da düz
            sözlükler. Okunan alanlar: severity, source, chain_verified,
            recommended_action, team_id, token.
        distinct_actors: biliniyorsa farklı aktör/IP sayısı; verilmezse olay
            sayısından türetilir.
    """
    items = list(events)
    signals: list[BehaviorSignal] = []
    score = 0

    # 1) Şiddet tırmanışı: en yüksek ve ortalama şiddet.
    severities = [
        str(_get(e, "severity", "")).lower() for e in items
    ]
    severities = [s for s in severities if s in _SEVERITY_ORDER]
    if severities:
        top = max(severities, key=lambda s: _SEVERITY_ORDER[s])
        if _SEVERITY_ORDER[top] >= 3:
            # Tek bir critical olay bile en az "medium" niyet taşır.
            w = 30 if top == "critical" else 15
            score += w
            signals.append(BehaviorSignal("severity_escalation", w,
                                          f"en yüksek şiddet: {top}"))

    # 2) Kanıt zinciri kurcalama şüphesi — en ağır sinyal.
    tampered = sum(1 for e in items if _get(e, "chain_verified") is False)
    if tampered:
        score += 35
        signals.append(BehaviorSignal("evidence_tamper", 35,
                                      f"{tampered} olayda zincir doğrulanamadı"))

    # 3) Çok yüzeyli / yaygın sızıntı: farklı bağlam + yüksek olay sayısı.
    contexts: set[str] = set()
    for e in items:
        for ctx in (_get(e, "contexts") or []):
            contexts.add(str(ctx))
    if len(contexts) >= 2:
        score += 20
        signals.append(BehaviorSignal("multi_surface", 20,
                                      f"{len(contexts)} farklı bağlam sızdı"))
    if len(items) >= 5:
        score += 15
        signals.append(BehaviorSignal("high_volume", 15,
                                      f"{len(items)} olay (yaygın aktivite)"))

    # 4) Dağıtık kaynak: birden çok aktör → koordineli kampanya.
    actors = distinct_actors if distinct_actors is not None else len({
        _get(e, "token") for e in items if _get(e, "token")
    })
    if actors >= 3:
        score += 20
        signals.append(BehaviorSignal("distributed", 20,
                                      f"{actors} farklı aktör/token"))
    elif actors == 2:
        score += 10
        signals.append(BehaviorSignal("distributed", 10, "2 farklı aktör/token"))

    # 5) Otomatik/tarama davranışı: eskalasyon önerisi tekrarlı.
    escalations = sum(
        1 for e in items if str(_get(e, "recommended_action", "")).lower() == "escalate"
    )
    if escalations >= 2:
        score += 10
        signals.append(BehaviorSignal("repeat_escalation", 10,
                                      f"{escalations} kez eskalasyon"))

    score = min(score, 100)
    level = _intent_level(score)

    # Sofistike davranış: kurcalama veya çok yüzeyli + dağıtık kombinasyonu.
    if tampered or (len(contexts) >= 2 and actors >= 3):
        sophistication = "advanced"
    elif len(contexts) >= 2 or actors >= 2 or _SEVERITY_ORDER.get(
        max(severities, key=lambda s: _SEVERITY_ORDER[s], default="low"), 0
    ) >= 3:
        sophistication = "targeted"
    else:
        sophistication = "opportunistic"

    return BehaviorProfile(
        intent_score=score,
        intent_level=level,
        sophistication=sophistication,
        signals=signals,
        event_count=len(items),
        recommended_action=_action_for(level),
    )


def analyze_records(records: Iterable[Any]) -> BehaviorProfile:
    """`BeaconTriageStore.list_for_token` çıktısı için kolaylık sarmalayıcı."""
    return analyze(records)


__all__ = [
    "BehaviorProfile",
    "BehaviorSignal",
    "analyze",
    "analyze_records",
]
