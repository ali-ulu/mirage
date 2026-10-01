"""
MIRAGE — Otonom deception orkestrasyonu.

`HoneypotEngine` tek bir oturumu yönetir; bu katman oturumları **otomatik**
açar, saldırgan mesaj dizisiyle (playbook) besler, sızıntıyı yakalar ve
sızıntı sonrası decoy'u **döndürür** (rotate). Böylece deception, elle
müdahale olmadan çalışır ve yakalama sonrası sahte kimlik tazelenir.

Tasarım (mevcut katmanlarla tutarlı):
  - `HoneypotEngine`'i yeniden kullanır (tek sorumluluk, DRY).
  - Deterministik akış; LLM yalnızca yanıt üretiminde opsiyoneldir.
  - Fail-safe: tek bir mesaj hata verse bile playbook akışı bozulmaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from .honeypot import HoneypotEngine, HoneypotPersona, HoneypotSession


@dataclass
class DeceptionOutcome:
    session_id: str
    turns: int
    leaked: bool
    canary_hits: list[str]
    stopped_reason: str  # "leak" | "exhausted" | "closed"
    rotated_to: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turns": self.turns,
            "leaked": self.leaked,
            "canary_hits": self.canary_hits,
            "stopped_reason": self.stopped_reason,
            "rotated_to": self.rotated_to,
        }


class DeceptionOrchestrator:
    """
    Honeypot oturumlarını otomatik sürer ve sızıntı sonrası döndürür.

    Args:
        engine: kullanılacak `HoneypotEngine` (verilmezse yeni bir tane).
        max_turns: bir playbook'ta en fazla kaç saldırgan mesajı işlenecek.
        rotate_on_leak: sızıntı yakalanınca taze bir decoy oturumu aç.
        on_leak: opsiyonel `(session, outcome) -> None`; yakalamada çağrılır.
    """

    def __init__(
        self,
        *,
        engine: Optional[HoneypotEngine] = None,
        max_turns: int = 20,
        rotate_on_leak: bool = True,
        on_leak: Optional[Callable[[HoneypotSession, DeceptionOutcome], None]] = None,
    ):
        self.engine = engine if engine is not None else HoneypotEngine()
        self.max_turns = max(1, int(max_turns))
        self.rotate_on_leak = rotate_on_leak
        self.on_leak = on_leak
        self.outcomes: list[DeceptionOutcome] = []
        self._closed: set[str] = set()

    @property
    def active_sessions(self) -> dict[str, HoneypotSession]:
        return {sid: s for sid, s in self.engine.sessions.items() if sid not in self._closed}

    async def run_playbook(
        self,
        messages: Iterable[str],
        *,
        token: Optional[str] = None,
        context: Optional[str] = None,
        persona: Optional[HoneypotPersona] = None,
        provider: Any = None,
    ) -> DeceptionOutcome:
        """
        Bir saldırgan mesaj dizisini yeni bir oturumda sürer.

        Sızıntı yakalanınca (ve `rotate_on_leak`) oturum kapatılır ve taze bir
        decoy açılır; dönen `DeceptionOutcome.rotated_to` yeni oturumun id'sidir.
        """
        session = await self.engine.create_session(
            token=token, context=context, persona=persona, provider=provider
        )
        turns = 0
        leaked = False
        hits: list[str] = []
        reason = "exhausted"

        for message in messages:
            if turns >= self.max_turns:
                reason = "exhausted"
                break
            try:
                turn = await self.engine.respond(session, message, provider=provider)
            except Exception:  # tek mesaj hatası akışı bozmaz (fail-safe)
                continue
            turns += 1
            if turn.leaked:
                leaked = True
                hits = turn.canary_hits
                reason = "leak"
                break

        outcome = DeceptionOutcome(
            session_id=session.session_id,
            turns=turns,
            leaked=leaked,
            canary_hits=hits,
            stopped_reason=reason,
        )

        if leaked and self.rotate_on_leak:
            self._closed.add(session.session_id)
            fresh = await self.engine.create_session(token=token, context=context)
            outcome.rotated_to = fresh.session_id

        self.outcomes.append(outcome)
        if leaked:
            self._notify(session, outcome)
        return outcome

    def close(self, session_id: str) -> bool:
        """Bir oturumu kapatır (aktif listeden çıkarır)."""
        if session_id in self.engine.sessions and session_id not in self._closed:
            self._closed.add(session_id)
            return True
        return False

    def sweep(self, *, older_than_seconds: float, now: Optional[datetime] = None) -> list[str]:
        """
        Belirtilen yaştan eski oturumları kapatır (deterministik, enjekte
        edilebilir `now` ile test edilebilir). Kapatılan id'leri döndürür.
        """
        ref = now or datetime.now(timezone.utc)
        closed: list[str] = []
        for sid, session in list(self.active_sessions.items()):
            created = _parse_ts(session.created_at)
            if created is None:
                continue
            if (ref - created).total_seconds() >= older_than_seconds:
                self._closed.add(sid)
                closed.append(sid)
        return closed

    def summary(self) -> dict[str, Any]:
        """Orkestrasyon özeti (playbook/oturum/yakalama sayıları)."""
        leaked = sum(1 for o in self.outcomes if o.leaked)
        return {
            "playbooks": len(self.outcomes),
            "sessions": len(self.engine.sessions),
            "active_sessions": len(self.active_sessions),
            "leaks": leaked,
            "turns": sum(o.turns for o in self.outcomes),
        }

    def _notify(self, session: HoneypotSession, outcome: DeceptionOutcome) -> None:
        if self.on_leak is None:
            return
        try:
            self.on_leak(session, outcome)
        except Exception:  # yakalama yolu akışı bozmaz
            import logging

            logging.getLogger("mirage.deception").warning(
                "deception on_leak sink failed", exc_info=True
            )


def _parse_ts(value: str) -> Optional[datetime]:
    try:
        ts = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


__all__ = ["DeceptionOrchestrator", "DeceptionOutcome"]
