"""MIRAGE — Agent katmanı.

Mevcut motor uçlarını (synthesizer, honeytoken registry, kanıt/triyaj) birer
**tool** olarak kullanan opsiyonel ajanlar. Çekirdek deterministik kalır; ajan
katmanı yalnızca planlama/karar zenginleştirmesi sağlar.
"""
from .apply import apply_decoy_plan
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
    "build_marker",
    "build_planner_messages",
    "detect_canaries",
    "plan_decoy_schema",
    "render_canary",
    "schema_summary",
]
