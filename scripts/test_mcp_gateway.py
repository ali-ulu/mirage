"""
PR — MCP gateway testleri.

Kapsam:
  - `score_server`: yetenek/araç ipuçları, taşıma riskleri, 0..100 sınırı, seviye.
  - `MCPGateway.evaluate`: allow/deny sunucu & araç, HTTPS zorunluluğu, azami risk.
  - `scan_hook`: izin verir / engeller / patlarsa fail-closed.
  - `audit_log` + `audit_summary`.
  - `default_policy_from_env`: env ayrıştırma (geçersiz max risk → critical).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage.mcp_gateway import (  # noqa: E402
    MCPGateway,
    MCPPolicy,
    MCPServerInfo,
    default_policy_from_env,
    score_server,
)


def _server(**kw) -> MCPServerInfo:
    kw.setdefault("name", "srv")
    return MCPServerInfo(**kw)


# ---------------------------------------------------------------------------
# score_server
# ---------------------------------------------------------------------------
def test_low_risk_stdio_server():
    risk = score_server(_server())
    assert risk.score == 0 and risk.level == "low" and risk.reasons == []


def test_exec_tool_raises_risk():
    risk = score_server(_server(tools=["run_shell"]))
    assert risk.score >= 40 and risk.level in ("medium", "high", "critical")


def test_credential_tool_is_high():
    risk = score_server(_server(tools=["get_credentials"]))
    assert risk.score >= 35


def test_capabilities_contribute():
    risk = score_server(_server(capabilities=["filesystem", "network"]))
    assert risk.score == 40
    assert any("dosya" in r for r in risk.reasons)


def test_http_without_auth_raises():
    risk = score_server(_server(transport="http", url="https://x", authenticated=False))
    assert risk.score == 20


def test_plain_http_transport_raises():
    risk = score_server(_server(transport="http", url="http://x", authenticated=True))
    assert risk.score == 15
    assert any("http://" in r for r in risk.reasons)


def test_score_is_capped_at_100():
    risk = score_server(_server(
        capabilities=["exec", "credentials", "network", "filesystem", "database", "sampling"],
        tools=["run_shell", "get_credentials"],
        transport="http", url="http://x", authenticated=False,
    ))
    assert risk.score == 100 and risk.level == "critical"


# ---------------------------------------------------------------------------
# policy decisions
# ---------------------------------------------------------------------------
def test_allows_benign_call():
    gw = MCPGateway(policy=MCPPolicy())
    d = gw.evaluate(_server(), "search")
    assert d.allowed is True and d.reason == "izinli"


def test_denied_server():
    gw = MCPGateway(policy=MCPPolicy(denied_servers=("srv",)))
    assert gw.evaluate(_server(), "search").allowed is False


def test_allow_list_blocks_unknown_server():
    gw = MCPGateway(policy=MCPPolicy(allowed_servers=("other",)))
    d = gw.evaluate(_server(), "search")
    assert d.allowed is False and "allow-listesinde değil" in d.reason


def test_denied_tool():
    gw = MCPGateway(policy=MCPPolicy(denied_tools=("run_shell",)))
    assert gw.evaluate(_server(), "run_shell").allowed is False


def test_tool_allow_list():
    gw = MCPGateway(policy=MCPPolicy(allowed_tools=("search",)))
    assert gw.evaluate(_server(), "search").allowed is True
    assert gw.evaluate(_server(), "other").allowed is False


def test_require_https():
    gw = MCPGateway(policy=MCPPolicy(require_https=True))
    http_srv = _server(transport="http", url="http://x", authenticated=True)
    https_srv = _server(transport="http", url="https://x", authenticated=True)
    assert gw.evaluate(http_srv, "search").allowed is False
    assert gw.evaluate(https_srv, "search").allowed is True


def test_max_risk_level_blocks_high_risk():
    gw = MCPGateway(policy=MCPPolicy(max_risk_level="low"))
    risky = _server(tools=["run_shell"])
    d = gw.evaluate(risky, "run_shell")
    assert d.allowed is False and "azami" in d.reason


def test_risk_boundary_allows_equal_level():
    gw = MCPGateway(policy=MCPPolicy(max_risk_level="medium"))
    medium = _server(tools=["run_shell"])  # score 40 -> medium
    assert score_server(medium).level == "medium"
    assert gw.evaluate(medium, "run_shell").allowed is True


# ---------------------------------------------------------------------------
# scan hook
# ---------------------------------------------------------------------------
def test_scan_hook_passes_through():
    seen: list[str] = []
    gw = MCPGateway(scan_hook=lambda text: seen.append(text))
    d = gw.evaluate(_server(), "search", arguments={"q": "hello"})
    assert d.allowed is True and seen == ['{"q": "hello"}']


def test_scan_hook_blocks():
    def hook(text: str) -> None:
        raise RuntimeError("leak")

    gw = MCPGateway(scan_hook=hook)
    d = gw.evaluate(_server(), "search", arguments={"q": "x"})
    assert d.allowed is False and "tarama kancası engelledi" in d.reason


def test_scan_hook_string_arguments_passed_raw():
    seen: list[str] = []
    gw = MCPGateway(scan_hook=lambda text: seen.append(text))
    gw.evaluate(_server(), "search", arguments="raw-text")
    assert seen == ["raw-text"]


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------
def test_audit_log_and_summary():
    gw = MCPGateway(policy=MCPPolicy(denied_tools=("run_shell",)))
    gw.evaluate(_server(), "search", actor="agent-1")
    gw.evaluate(_server(tools=["run_shell"]), "run_shell", actor="agent-1")
    summary = gw.audit_summary()
    assert summary["total"] == 2 and summary["allowed"] == 1 and summary["denied"] == 1
    assert gw.audit_log[0]["actor"] == "agent-1"
    assert gw.audit_log[1]["allowed"] is False


def test_decision_to_dict():
    gw = MCPGateway()
    d = gw.evaluate(_server(), "search")
    payload = d.to_dict()
    assert payload["server"] == "srv" and payload["risk"]["level"] == "low"


# ---------------------------------------------------------------------------
# env policy
# ---------------------------------------------------------------------------
def test_default_policy_from_env(monkeypatch):
    monkeypatch.setenv("MIRAGE_MCP_ALLOW_SERVERS", "a, b")
    monkeypatch.setenv("MIRAGE_MCP_DENY_TOOLS", "run_shell")
    monkeypatch.setenv("MIRAGE_MCP_MAX_RISK", "medium")
    monkeypatch.setenv("MIRAGE_MCP_REQUIRE_HTTPS", "1")
    p = default_policy_from_env()
    assert p.allowed_servers == ("a", "b")
    assert p.denied_tools == ("run_shell",)
    assert p.max_risk_level == "medium" and p.require_https is True


def test_default_policy_invalid_max_risk_falls_back(monkeypatch):
    monkeypatch.setenv("MIRAGE_MCP_MAX_RISK", "bogus")
    assert default_policy_from_env().max_risk_level == "critical"
