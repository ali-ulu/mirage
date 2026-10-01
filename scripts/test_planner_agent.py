"""
MIRAGE — Planner Agent testleri.

Strateji:
  - Heuristic yol: gerçek `profile_column` ile çalışır (mock yok).
  - LLM yolu: `LLMProvider` arayüzü enjekte edilir (ağa çıkılmaz), triyaj
    testleriyle aynı desen.
  - Güvenlik kısıtı: model bir tanımlayıcıyı decoy yapmaya çalışsa da korunur.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage import server  # noqa: E402
from mirage.agent import (  # noqa: E402
    build_planner_messages,
    plan_decoy_schema,
    schema_summary,
)
from mirage.llm import LLMProvider, LLMResponse  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "customer_id": [f"C{i:04d}" for i in range(40)],
            "full_name": [f"Person {i}" for i in range(40)],
            "email": [f"user{i}@example.com" for i in range(40)],
            "salary": [30000 + i * 137 for i in range(40)],
            "country": (["TR", "DE", "US", "FR"] * 10),
            "notes": [f"note text number {i} lorem ipsum" for i in range(40)],
        }
    )


class _FakeProvider(LLMProvider):
    name = "fake"

    def __init__(self, text: str):
        self._text = text

    async def complete(self, messages, *, max_tokens=512, temperature=0.0, json_mode=False):
        return LLMResponse(text=self._text, provider=self.name, model="fake-1")


class _ExplodingProvider(LLMProvider):
    name = "boom"

    async def complete(self, messages, *, max_tokens=512, temperature=0.0, json_mode=False):
        raise RuntimeError("provider down")


# ---------------------------------------------------------------------------
# Heuristic yol
# ---------------------------------------------------------------------------
def test_heuristic_keeps_identifier_columns():
    plan = _run(plan_decoy_schema(_df()))
    assert plan.source == "heuristic"
    assert "customer_id" in plan.kept_columns


def test_heuristic_decoys_sensitive_columns():
    plan = _run(plan_decoy_schema(_df()))
    decoys = set(plan.decoy_columns)
    for col in ("full_name", "email", "salary", "notes", "country"):
        assert col in decoys, col


def test_heuristic_decisions_cover_every_column():
    df = _df()
    plan = _run(plan_decoy_schema(df))
    assert len(plan.decisions) == len(df.columns)
    assert set(plan.decoy_columns).isdisjoint(plan.kept_columns)


def test_heuristic_marks_identifiers_low_risk_for_decoy():
    plan = _run(plan_decoy_schema(_df()))
    by_name = {d.name: d for d in plan.decisions}
    assert by_name["customer_id"].disposition == "keep"
    assert by_name["email"].sensitivity == "high"


def test_heuristic_keeps_uuid_formatted_column():
    df = pd.DataFrame(
        {"row_uuid": [f"{i:08d}-1111-2222-3333-444455556666" for i in range(40)]}
    )
    plan = _run(plan_decoy_schema(df))
    assert "row_uuid" in plan.kept_columns


# ---------------------------------------------------------------------------
# schema_summary
# ---------------------------------------------------------------------------
def test_schema_summary_reports_types_and_cardinality():
    summary = schema_summary(_df())
    by_name = {e["name"]: e for e in summary}
    assert by_name["country"]["col_type"] == "categorical"
    assert by_name["country"]["cardinality"] == 4
    assert by_name["email"]["col_type"] == "formatted"
    assert by_name["email"]["format_kind"] == "email"
    # JSON-serileştirilebilir olmalı
    json.dumps(summary)


def test_build_planner_messages_shape():
    msgs = build_planner_messages(schema_summary(_df()))
    assert len(msgs) == 2
    assert msgs[0].role == "system"
    assert msgs[1].role == "user"
    assert "decoy" in msgs[0].content


# ---------------------------------------------------------------------------
# LLM yolu
# ---------------------------------------------------------------------------
def test_llm_plan_is_honored():
    text = json.dumps(
        {
            "strategy": "model planı",
            "columns": [
                {"name": "customer_id", "disposition": "keep", "rationale": "key"},
                {"name": "full_name", "disposition": "decoy", "rationale": "pii"},
                {"name": "email", "disposition": "decoy", "rationale": "pii"},
                {"name": "salary", "disposition": "decoy", "rationale": "sensitive"},
                {"name": "country", "disposition": "keep", "rationale": "low risk"},
                {"name": "notes", "disposition": "decoy", "rationale": "free text"},
            ],
        }
    )
    plan = _run(plan_decoy_schema(_df(), provider=_FakeProvider(text)))
    assert plan.source == "llm:fake"
    assert plan.strategy == "model planı"
    assert "country" in plan.kept_columns


def test_llm_cannot_decoy_identifier_column():
    """Model `customer_id`'yi decoy yapmaya çalışsa da güvenlik gereği korunur."""
    text = json.dumps(
        {
            "strategy": "riskli plan",
            "columns": [
                {"name": "customer_id", "disposition": "decoy", "rationale": "model hatası"},
                {"name": "full_name", "disposition": "decoy", "rationale": "pii"},
                {"name": "email", "disposition": "decoy", "rationale": "pii"},
                {"name": "salary", "disposition": "decoy", "rationale": "sensitive"},
                {"name": "country", "disposition": "decoy", "rationale": "x"},
                {"name": "notes", "disposition": "decoy", "rationale": "x"},
            ],
        }
    )
    plan = _run(plan_decoy_schema(_df(), provider=_FakeProvider(text)))
    assert "customer_id" in plan.kept_columns


def test_llm_invalid_json_falls_back_to_heuristic():
    plan = _run(plan_decoy_schema(_df(), provider=_FakeProvider("not json at all")))
    assert plan.source == "heuristic"


def test_llm_missing_columns_falls_back_to_heuristic():
    text = json.dumps(
        {
            "strategy": "eksik",
            "columns": [{"name": "email", "disposition": "decoy", "rationale": "x"}],
        }
    )
    plan = _run(plan_decoy_schema(_df(), provider=_FakeProvider(text)))
    assert plan.source == "heuristic"


def test_llm_invalid_disposition_falls_back():
    text = json.dumps(
        {
            "strategy": "geçersiz",
            "columns": [
                {"name": c, "disposition": "delete", "rationale": "x"} for c in _df().columns
            ],
        }
    )
    plan = _run(plan_decoy_schema(_df(), provider=_FakeProvider(text)))
    assert plan.source == "heuristic"


def test_llm_error_falls_back_to_heuristic():
    plan = _run(plan_decoy_schema(_df(), provider=_ExplodingProvider()))
    assert plan.source == "heuristic"


def test_plan_to_dict_is_serializable():
    plan = _run(plan_decoy_schema(_df()))
    payload = plan.to_dict()
    json.dumps(payload)
    assert payload["decoy_columns"] == plan.decoy_columns


# ---------------------------------------------------------------------------
# HTTP endpoint (/agent/plan)
# ---------------------------------------------------------------------------
def test_agent_plan_endpoint_returns_plan(monkeypatch):
    monkeypatch.delenv("MIRAGE_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = TestClient(server.app)
    res = client.post("/agent/plan", json={"data": _df().to_dict(orient="records")})
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "heuristic"
    assert "customer_id" in body["kept_columns"]
    assert "email" in body["decoy_columns"]


def test_agent_plan_endpoint_rejects_empty_data():
    client = TestClient(server.app)
    res = client.post("/agent/plan", json={"data": []})
    assert res.status_code == 422
