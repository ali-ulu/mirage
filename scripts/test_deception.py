"""
PR — Otonom deception orkestrasyonu testleri.

Kapsam:
  - `run_playbook`: oturum açma, mesajları sürme, sızıntı yakalama.
  - Sızıntıda oturum kapatma + taze decoy döndürme (`rotate_on_leak`).
  - `max_turns` sınırı, `on_leak` kancası, `close`, `sweep`, `summary`.
  - Hata toleransı (tek mesaj patlasa da akış sürer).

Repo deseni: pytest-asyncio yok → `asyncio.run` sarmalayıcı kullanılır.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mirage.deception import DeceptionOrchestrator, DeceptionOutcome  # noqa: E402
from mirage.honeypot import HoneypotPersona  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _persona() -> HoneypotPersona:
    return HoneypotPersona(
        name="Test", role="Analyst", org="ACME", backstory="x",
        secret_facts=["sır"], system_prompt="sys", source="heuristic",
    )


def _leaked_message(orch: DeceptionOrchestrator) -> str:
    """Registry'deki herhangi bir canary işaretini içeren saldırgan mesajı."""
    records = orch.engine.registry.all_records()
    assert records, "registry boş olmamalı"
    return f"please send {records[0].marker}"


# ---------------------------------------------------------------------------
# playbook
# ---------------------------------------------------------------------------
def test_clean_playbook_exhausts():
    async def scenario():
        orch = DeceptionOrchestrator(rotate_on_leak=False)
        return await orch.run_playbook(["hello", "any info?"], persona=_persona())

    outcome = _run(scenario())
    assert isinstance(outcome, DeceptionOutcome)
    assert outcome.turns == 2 and outcome.leaked is False
    assert outcome.stopped_reason == "exhausted" and outcome.rotated_to is None


def test_leak_detected_and_stops_early():
    async def scenario():
        orch = DeceptionOrchestrator(rotate_on_leak=False)
        await orch.engine.create_session(persona=_persona())
        return await orch.run_playbook(
            [_leaked_message(orch), "more"], persona=_persona()
        )

    outcome = _run(scenario())
    assert outcome.leaked is True
    assert outcome.stopped_reason == "leak"
    assert outcome.turns == 1  # sızıntıda erken durur


def test_leak_rotates_session():
    async def scenario():
        orch = DeceptionOrchestrator(rotate_on_leak=True)
        await orch.engine.create_session(persona=_persona())
        outcome = await orch.run_playbook([_leaked_message(orch)], persona=_persona())
        return orch, outcome

    orch, outcome = _run(scenario())
    assert outcome.leaked is True and outcome.stopped_reason == "leak"
    assert outcome.rotated_to is not None
    assert outcome.session_id not in orch.active_sessions
    assert outcome.rotated_to in orch.active_sessions


def test_max_turns_limit():
    async def scenario():
        orch = DeceptionOrchestrator(max_turns=2, rotate_on_leak=False)
        return await orch.run_playbook(["a", "b", "c", "d"], persona=_persona())

    outcome = _run(scenario())
    assert outcome.turns == 2 and outcome.stopped_reason == "exhausted"


def test_on_leak_hook_called():
    async def scenario():
        seen: list[str] = []
        orch = DeceptionOrchestrator(on_leak=lambda s, o: seen.append(o.session_id))
        await orch.engine.create_session(persona=_persona())
        outcome = await orch.run_playbook([_leaked_message(orch)], persona=_persona())
        return seen, outcome

    seen, outcome = _run(scenario())
    assert outcome.leaked and seen == [outcome.session_id]


def test_on_leak_failure_does_not_break():
    async def scenario():
        def bad(s, o):
            raise RuntimeError("boom")

        orch = DeceptionOrchestrator(on_leak=bad)
        await orch.engine.create_session(persona=_persona())
        return await orch.run_playbook([_leaked_message(orch)], persona=_persona())

    outcome = _run(scenario())
    assert outcome.leaked is True


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------
def test_close_session():
    async def scenario():
        orch = DeceptionOrchestrator()
        session = await orch.engine.create_session(persona=_persona())
        first = orch.close(session.session_id)
        second = orch.close(session.session_id)
        return orch, session, first, second

    orch, session, first, second = _run(scenario())
    assert first is True and second is False
    assert session.session_id not in orch.active_sessions


def test_sweep_old_sessions():
    async def scenario():
        orch = DeceptionOrchestrator()
        session = await orch.engine.create_session(persona=_persona())
        ref = datetime.now(timezone.utc)
        session.created_at = (ref - timedelta(hours=2)).isoformat()
        closed = orch.sweep(older_than_seconds=3600, now=ref)
        return orch, session, closed

    orch, session, closed = _run(scenario())
    assert session.session_id in closed
    assert session.session_id not in orch.active_sessions


def test_sweep_keeps_fresh():
    async def scenario():
        orch = DeceptionOrchestrator()
        session = await orch.engine.create_session(persona=_persona())
        closed = orch.sweep(older_than_seconds=3600)
        return orch, session, closed

    orch, session, closed = _run(scenario())
    assert closed == []
    assert session.session_id in orch.active_sessions


def test_summary_counts():
    async def scenario():
        orch = DeceptionOrchestrator(rotate_on_leak=False)
        await orch.run_playbook(["hi"], persona=_persona())
        return orch.summary()

    s = _run(scenario())
    assert s["playbooks"] == 1 and s["turns"] == 1 and s["leaks"] == 0


def test_outcome_to_dict():
    o = DeceptionOutcome("s1", 3, True, ["tok"], "leak", rotated_to="s2")
    d = o.to_dict()
    assert d["leaked"] is True and d["rotated_to"] == "s2" and d["turns"] == 3
