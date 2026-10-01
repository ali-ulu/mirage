"""MIRAGE — Şiddet seviyesi tek kaynağının sözleşme testleri."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import behavior, dlp, mcp_gateway, redteam, severity  # noqa: E402


def test_order_is_monotonic():
    order = severity.SEVERITY_ORDER
    assert order["low"] < order["medium"] < order["high"] < order["critical"]


def test_level_for_score_boundaries():
    f = severity.level_for_score
    assert f(0) == "low"
    assert f(29) == "low"
    assert f(30) == "medium"
    assert f(54) == "medium"
    assert f(55) == "high"
    assert f(79) == "high"
    assert f(80) == "critical"
    assert f(100) == "critical"


def test_exceeds_unknown_threshold_is_strict():
    assert severity.exceeds("critical", "high") is True
    assert severity.exceeds("low", "medium") is False
    # Bilinmeyen eşik en katı (99) kabul edilir → hiçbir seviye geçmez.
    assert severity.exceeds("critical", "bogus") is False


def test_modules_share_single_source():
    # Kopya sabit yok: tüm katmanlar aynı sözlük nesnesini kullanır.
    assert redteam._SEVERITY_ORDER is severity.SEVERITY_ORDER
    assert dlp._SEVERITY_ORDER is severity.SEVERITY_ORDER
    assert behavior._SEVERITY_ORDER is severity.SEVERITY_ORDER
    assert mcp_gateway._RISK_ORDER is severity.SEVERITY_ORDER


def test_score_to_level_uses_shared_thresholds():
    # mcp_gateway risk puanı ve behavior niyet skoru aynı eşikleri kullanır.
    assert mcp_gateway.level_for_score is severity.level_for_score
    assert behavior.level_for_score is severity.level_for_score
