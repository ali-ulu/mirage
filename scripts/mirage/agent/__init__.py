"""MIRAGE — Agent katmanı.

Mevcut motor uçlarını (synthesizer, honeytoken registry, kanıt/triyaj) birer
**tool** olarak kullanan opsiyonel ajanlar. Çekirdek deterministik kalır; ajan
katmanı yalnızca planlama/karar zenginleştirmesi sağlar.
"""
from .apply import apply_decoy_plan
from .canary_evidence import resolve_chain_binding
from .canary_triage import (
    build_canary_triage_messages,
    heuristic_canary_triage,
    triage_canary,
)
from .middleware import (
    AgentScanMiddleware,
    install_agent_scan_middleware,
    scan_middleware_enabled,
    should_scan_path,
)
from .guard import (
    AgentGuard,
    AgentGuardMiddleware,
    GuardBlocked,
    build_guard_sink,
    get_agent_guard,
    guard_enabled,
    guard_persist_enabled,
    install_agent_guard_middleware,
)
from .outbound import OutboundLeakError, OutboundScanner
from .runtime import evaluate_rules, scan_text_for_leaks
from .planner import (
    ColumnDecision,
    DecoyPlan,
    build_planner_messages,
    plan_decoy_schema,
    schema_summary,
)
from .prompt_canary import (
    CanaryRegistry,
    PromptCanary,
    build_marker,
    detect_canaries,
    render_canary,
)

__all__ = [
    "AgentGuard",
    "AgentGuardMiddleware",
    "AgentScanMiddleware",
    "CanaryRegistry",
    "ColumnDecision",
    "DecoyPlan",
    "GuardBlocked",
    "OutboundLeakError",
    "OutboundScanner",
    "build_guard_sink",
    "get_agent_guard",
    "guard_enabled",
    "guard_persist_enabled",
    "install_agent_guard_middleware",
    "PromptCanary",
    "apply_decoy_plan",
    "build_canary_triage_messages",
    "build_marker",
    "build_planner_messages",
    "detect_canaries",
    "evaluate_rules",
    "heuristic_canary_triage",
    "install_agent_scan_middleware",
    "plan_decoy_schema",
    "render_canary",
    "resolve_chain_binding",
    "scan_middleware_enabled",
    "schema_summary",
    "scan_text_for_leaks",
    "should_scan_path",
    "triage_canary",
]
