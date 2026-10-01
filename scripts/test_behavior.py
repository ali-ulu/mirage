"""
PR — Ajan davranış analitiği testleri.

Kapsam:
  - `analyze`: şiddet tırmanışı, kanıt kurcalama, çok yüzeyli/yaygın sızıntı,
    dağıtık kaynak, tekrarlı eskalasyon sinyalleri ve skor/seviye eşikleri.
  - Sofistike davranış sınıflandırması.
  - `TriageRecord` benzeri dataclass girdisi + `analyze_records` sarmalayıcı.
  - Boş/bozuk girdi fail-safe.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage.behavior import BehaviorProfile, analyze, analyze_records  # noqa: E402


def _ev(**kw) -> dict:
    return kw


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------
def test_empty_events_is_low():
    p = analyze([])
    assert p.intent_score == 0 and p.intent_level == "low"
    assert p.sophistication == "opportunistic" and p.event_count == 0


def test_single_low_event_ignored():
    p = analyze([_ev(severity="low", recommended_action="ignore")])
    assert p.intent_level == "low" and p.recommended_action == "ignore"


def test_critical_severity_raises_intent():
    p = analyze([_ev(severity="critical")])
    assert p.intent_score >= 25 and p.intent_level in ("medium", "high", "critical")


def test_evidence_tamper_is_strongest_signal():
    p = analyze([_ev(severity="high", chain_verified=False)])
    assert any(s.name == "evidence_tamper" for s in p.signals)
    assert p.intent_score >= 35


def test_multi_surface_context():
    p = analyze([
        _ev(severity="high", contexts=["system_prompt"]),
        _ev(severity="high", contexts=["rag_document"]),
    ])
    assert any(s.name == "multi_surface" for s in p.signals)


def test_high_volume():
    p = analyze([_ev(severity="medium") for _ in range(5)])
    assert any(s.name == "high_volume" for s in p.signals)


def test_distributed_actors():
    p = analyze([_ev(severity="medium")], distinct_actors=3)
    assert any(s.name == "distributed" and s.weight == 20 for s in p.signals)


def test_repeat_escalation():
    p = analyze([
        _ev(severity="critical", recommended_action="escalate"),
        _ev(severity="critical", recommended_action="escalate"),
    ])
    assert any(s.name == "repeat_escalation" for s in p.signals)


# ---------------------------------------------------------------------------
# scoring / levels
# ---------------------------------------------------------------------------
def test_score_capped_at_100():
    events = [_ev(severity="critical", chain_verified=False, recommended_action="escalate")
              for _ in range(6)]
    for e in events:
        e["contexts"] = ["system_prompt", "rag_document"]
    p = analyze(events, distinct_actors=4)
    assert p.intent_score == 100 and p.intent_level == "critical"
    assert p.recommended_action == "escalate"


def test_targeted_sophistication():
    p = analyze([
        _ev(severity="high", contexts=["system_prompt"]),
        _ev(severity="high", contexts=["rag_document"]),
    ])
    assert p.sophistication == "targeted"


def test_advanced_sophistication_with_tamper():
    p = analyze([_ev(severity="critical", chain_verified=False)])
    assert p.sophistication == "advanced"


def test_advanced_sophistication_multi_surface_distributed():
    p = analyze([
        _ev(severity="high", contexts=["system_prompt"]),
        _ev(severity="high", contexts=["rag_document"]),
    ], distinct_actors=3)
    assert p.sophistication == "advanced"


# ---------------------------------------------------------------------------
# inputs / fail-safe
# ---------------------------------------------------------------------------
def test_accepts_dataclass_like_records():
    class Rec:
        def __init__(self, severity, chain_verified=None, recommended_action=None):
            self.severity = severity
            self.chain_verified = chain_verified
            self.recommended_action = recommended_action
            self.contexts = []

    p = analyze([Rec("critical"), Rec("high")])
    assert p.event_count == 2 and p.intent_score > 0


def test_unknown_fields_ignored():
    p = analyze([_ev(severity="medium", nonsense=object())])
    assert p.event_count == 1


def test_invalid_severity_ignored():
    p = analyze([_ev(severity="bogus")])
    assert p.intent_level == "low"


def test_profile_to_dict():
    payload = analyze([_ev(severity="critical", chain_verified=False)]).to_dict()
    assert payload["intent_level"] in ("high", "critical")
    assert isinstance(payload["signals"], list)
    assert {"name", "weight", "detail"} <= set(payload["signals"][0])


def test_analyze_records_wrapper():
    p = analyze_records([_ev(severity="high")])
    assert isinstance(p, BehaviorProfile) and p.event_count == 1
