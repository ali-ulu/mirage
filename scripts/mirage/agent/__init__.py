"""MIRAGE — Agent katmanı.

Mevcut motor uçlarını (synthesizer, honeytoken registry, kanıt/triyaj) birer
**tool** olarak kullanan opsiyonel ajanlar. Çekirdek deterministik kalır; ajan
katmanı yalnızca planlama/karar zenginleştirmesi sağlar.
"""
from .apply import apply_decoy_plan
from .canary_evidence import resolve_chain_binding
from .canary_triage import build_canary_triage_messages, triage_canary
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
    "CanaryRegistry",
    "ColumnDecision",
    "DecoyPlan",
    "PromptCanary",
    "apply_decoy_plan",
    "build_canary_triage_messages",
    "build_marker",
    "build_planner_messages",
    "detect_canaries",
    "evaluate_rules",
    "plan_decoy_schema",
    "render_canary",
    "resolve_chain_binding",
    "schema_summary",
    "scan_text_for_leaks",
    "triage_canary",
]
