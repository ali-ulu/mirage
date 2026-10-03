"""
MIRAGE — MCP gateway kalıcı denetim defteri testleri.

Kapsam:
  1. Sink verilmezse davranış değişmez (bellek içi audit_log).
  2. Sink verilirse her karar kalıcı deftere yazılır.
  3. Denetim yazımı PATLARSA karar yine de geçerlidir (fail-safe ayrımı).
  4. Denetim kaydı kararı DEĞİŞTİRMEZ — kayıt üretmek kararı engellemez.
  5. Gateway kararı (allowed/denied) doğru şekilde kaydedilir.
  6. Sink yazmadan önce risk seviyesi eşikleri korunur.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mirage.mcp_gateway import MCPGateway, MCPPolicy, MCPServerInfo  # noqa: E402


# --- Yardımcılar ------------------------------------------------------------

def _server(**overrides) -> MCPServerInfo:
    base = {
        "name": "filesystem",
        "transport": "stdio",
        "capabilities": ["filesystem"],
        "tools": ["read_file"],
    }
    base.update(overrides)
    return MCPServerInfo(**base)


class _RecordingSink:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def __call__(self, entry: dict) -> None:
        self.entries.append(entry)


class _ExplodingSink:
    def __call__(self, entry: dict) -> None:
        raise RuntimeError("veritabanı erişilemiyor")


# --- Testler ----------------------------------------------------------------

def test_audit_sink_receives_every_decision():
    """Her gateway kararı kalıcı deftere yazılmalı."""
    sink = _RecordingSink()
    gateway = MCPGateway(policy=MCPPolicy(allowed_servers=("filesystem",)), audit_sink=sink)

    gateway.evaluate(_server(), "read_file", actor="agent-1")

    assert len(sink.entries) == 1
    entry = sink.entries[0]
    assert entry["server"] == "filesystem"
    assert entry["tool"] == "read_file"
    assert entry["actor"] == "agent-1"
    assert entry["allowed"] is True


def test_denied_call_is_audited():
    """Engellenen çağrı da denetimlenmeli — asıl önemli olan o."""
    sink = _RecordingSink()
    gateway = MCPGateway(policy=MCPPolicy(allowed_servers=("github",)), audit_sink=sink)

    decision = gateway.evaluate(_server(), "read_file", actor="agent-2")

    assert decision.allowed is False
    assert len(sink.entries) == 1
    assert sink.entries[0]["allowed"] is False
    assert sink.entries[0]["reason"]


def test_audit_log_still_populated_without_sink():
    """Sink yokken eski davranış korunur (bellek içi liste)."""
    gateway = MCPGateway(policy=MCPPolicy(allowed_servers=("filesystem",)))

    gateway.evaluate(_server(), "read_file")

    assert len(gateway.audit_log) == 1
    summary = gateway.audit_summary()
    assert summary["total"] == 1
    assert summary["allowed"] == 1


def test_sink_failure_does_not_break_decision():
    """
    KRİTİK: denetim yazımı patlarsa karar bozulmaz.

    Gateway'in işi çağrıyı engellemek/izin vermektir; denetim yazımı
    ise kanıt üretmektir. Eğer bunlar bağımlı olsaydı, bir veritabanı
    kesintisi tüm MCP trafiğini düşürürdü — fail-unsafe bir sistem.
    """
    gateway = MCPGateway(
        policy=MCPPolicy(allowed_servers=("filesystem",)),
        audit_sink=_ExplodingSink(),
    )

    decision = gateway.evaluate(_server(), "read_file")

    assert decision.allowed is True, "denetim hatası kararı bozmamalı"
    assert len(gateway.audit_log) == 1


def test_auditing_does_not_change_decision_outcome():
    """Aynı karar, sink'li ve sinksiz aynı olmalı."""
    policy = MCPPolicy(allowed_servers=("github",))

    without = MCPGateway(policy=policy)
    with_sink = MCPGateway(policy=policy, audit_sink=_RecordingSink())

    server = _server()
    a = without.evaluate(server, "read_file")
    b = with_sink.evaluate(server, "read_file")

    assert a.allowed == b.allowed
    assert a.risk.score == b.risk.score
    assert a.risk.level == b.risk.level


def test_risk_level_recorded_for_audit():
    """Risk seviyesi denetim kaydına yazılmalı (dashboard bunu gösterir)."""
    sink = _RecordingSink()
    gateway = MCPGateway(policy=MCPPolicy(allowed_servers=("filesystem",)), audit_sink=sink)

    risky = _server(
        name="shell",
        capabilities=["exec", "credentials"],
        tools=["exec_command", "get_credentials"],
    )
    gateway.evaluate(risky, "exec_command")

    entry = sink.entries[0]
    assert entry["risk_level"] in ("low", "medium", "high", "critical")
    assert entry["risk_score"] > 0
    assert entry["risk_level"] in ("high", "critical"), "riskli sunucu yüksek riskli olmalı"


def test_multiple_calls_accumulate():
    """Her çağrı ayrı kayıt üretmeli."""
    sink = _RecordingSink()
    gateway = MCPGateway(policy=MCPPolicy(allowed_servers=("filesystem",)), audit_sink=sink)

    gateway.evaluate(_server(), "read_file")
    gateway.evaluate(_server(), "read_file")
    gateway.evaluate(_server(), "list_dir")

    assert len(sink.entries) == 3
    assert [e["tool"] for e in sink.entries] == ["read_file", "read_file", "list_dir"]


def test_audit_entry_has_timestamp():
    """Kayıt zaman damgalı olmalı — denetim sırası zamanla anlam kazanır."""
    sink = _RecordingSink()
    gateway = MCPGateway(policy=MCPPolicy(allowed_servers=("filesystem",)), audit_sink=sink)

    gateway.evaluate(_server(), "read_file")

    assert sink.entries[0]["ts"]
    assert "T" in sink.entries[0]["ts"]