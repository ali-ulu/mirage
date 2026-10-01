"""
MIRAGE — SIEM/SOAR dışa aktarım (export).

Kanıt zinciri (`triggered_beacons`) ve triyaj defteri (`beacon_triage`)
kayıtlarını SIEM/SOAR'ın anlayacağı normalize edilmiş olaylara dönüştürür ve
bir sink üzerinden gönderir. Amaç: rakiplerin (Acalvio/Zscaler) sahip olduğu
SIEM entegrasyonunu, MIRAGE'in kurcalanamaz kanıt zinciriyle birlikte sunmak.

Tasarım (mevcut katmanlarla tutarlı):
  - `SiemSink` soyut arayüz (SOLID/DIP); `HecSink` (Splunk HTTP Event Collector),
    `WebhookSink` (genel/Sentinel/SOAR), `ConsoleSink` (yerel/tespit).
  - `build_events` saf/deterministik: kayıt → olay eşlemesi, LLM gerekmez.
  - `httpx` tembel/opsiyonel bağımlılık (LLM sağlayıcıları gibi); ağ yoksa
    `SiemError` yükseltilir, çekirdek bozulmaz.
  - Fail-safe: olay üretimi kayıt eksiklerine dayanıklıdır (eksik alan atlanır).

Env:
  MIRAGE_SIEM_SINK=hec|webhook|console|none   (varsayılan: none)
  MIRAGE_SIEM_URL=<endpoint>                  (hec/webhook için zorunlu)
  MIRAGE_SIEM_TOKEN=<token>                   (hec için; webhook'ta opsiyonel)
  MIRAGE_SIEM_INDEX=<splunk index>            (hec için opsiyonel)
  MIRAGE_SIEM_HEADERS={"Authorization":"..."} (webhook için opsiyonel JSON)
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any, Optional

# Triyaj şiddeti → SIEM severity (1-10).
_SEVERITY_TO_INT = {"low": 1, "medium": 4, "high": 7, "critical": 10}
_BEACON_SEVERITY = 3


class SiemError(RuntimeError):
    """Sink yapılandırılmamış veya gönderim başarısız olduğunda yükseltilir."""


# ---------------------------------------------------------------------------
# Olay üretimi (saf)
# ---------------------------------------------------------------------------
def _beacon_event(record: dict[str, Any], *, chain_verified: Optional[bool]) -> dict[str, Any]:
    seq = record.get("chain_seq")
    return {
        "timestamp": record.get("received_at"),
        "event": {
            "kind": "alert",
            "category": ["intrusion_detection"],
            "type": ["indicator"],
            "severity": _BEACON_SEVERITY,
            "action": "honeytoken-opened",
        },
        "message": f"MIRAGE beacon: honeytoken opened (token={record.get('token')}, seq={seq})",
        "mirage": {
            "record_type": "beacon",
            "token": record.get("token"),
            "chain_seq": seq,
            "chain_verified": chain_verified,
        },
        "source": {"ip": record.get("ip"), "user_agent": record.get("user_agent")},
    }


def _triage_event(record: Any) -> dict[str, Any]:
    d = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    severity = d.get("severity", "low")
    return {
        "timestamp": d.get("created_at"),
        "event": {
            "kind": "alert",
            "category": ["intrusion_detection"],
            "type": ["indicator"],
            "severity": _SEVERITY_TO_INT.get(severity, 1),
            "action": d.get("recommended_action"),
        },
        "message": (
            f"MIRAGE triage: {severity} → {d.get('recommended_action')} "
            f"(token={d.get('token')}, source={d.get('source')})"
        ),
        "mirage": {
            "record_type": "triage",
            "token": d.get("token"),
            "chain_seq": d.get("chain_seq"),
            "chain_verified": d.get("chain_verified"),
            "source": d.get("source"),
            "recommended_action": d.get("recommended_action"),
            "confidence": d.get("confidence"),
            "rationale": d.get("rationale"),
            "model": d.get("model"),
            "team_id": d.get("team_id"),
        },
        "source": {"ip": None, "user_agent": None},
    }


def build_events(
    *,
    evidence: Optional[list[dict[str, Any]]] = None,
    triage: Optional[list[Any]] = None,
    chain_verified: Optional[bool] = None,
) -> list[dict[str, Any]]:
    """Kanıt + triyaj kayıtlarını normalize edilmiş SIEM olaylarına çevirir."""
    events: list[dict[str, Any]] = []
    for record in evidence or []:
        if record.get("token"):
            events.append(_beacon_event(record, chain_verified=chain_verified))
    for record in triage or []:
        d = record.to_dict() if hasattr(record, "to_dict") else record
        if d.get("token"):
            events.append(_triage_event(record))
    return events


# ---------------------------------------------------------------------------
# Sink arayüzü (SOLID/DIP)
# ---------------------------------------------------------------------------
class SiemSink(ABC):
    """SIEM/SOAR olay gönderim arayüzü."""

    name = "sink"

    @abstractmethod
    async def send(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Olayları gönderir; teslim raporu döndürür (asla yut(a)maz)."""


class HecSink(SiemSink):
    """Splunk HTTP Event Collector sink'i."""

    name = "hec"

    def __init__(
        self,
        *,
        url: str,
        token: str,
        index: Optional[str] = None,
        sourcetype: str = "mirage:deception",
        source: str = "mirage",
        client: Any = None,
        timeout: float = 10.0,
    ):
        if not url or not token:
            raise SiemError("HecSink requires url and token")
        self.url = url.rstrip("/")
        self.token = token
        self.index = index
        self.sourcetype = sourcetype
        self.source = source
        self._client = client
        self._timeout = timeout

    def _body(self, events: list[dict[str, Any]]) -> str:
        lines = []
        for event in events:
            envelope: dict[str, Any] = {
                "event": event,
                "sourcetype": self.sourcetype,
                "source": self.source,
            }
            if self.index:
                envelope["index"] = self.index
            lines.append(json.dumps(envelope, ensure_ascii=False))
        return "\n".join(lines)

    async def send(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        import httpx  # opsiyonel bağımlılık: yalnızca gerçek gönderimde gerekir.

        endpoint = f"{self.url}/services/collector/event"
        headers = {
            "Authorization": f"Splunk {self.token}",
            "Content-Type": "application/json",
        }
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.post(endpoint, content=self._body(events), headers=headers)
        except httpx.HTTPError as exc:
            raise SiemError(f"HEC delivery failed: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        return {"sink": self.name, "sent": len(events), "status": resp.status_code,
                "ok": 200 <= resp.status_code < 300}


class WebhookSink(SiemSink):
    """Genel webhook sink'i (Sentinel/SOAR/özel toplayıcı)."""

    name = "webhook"

    def __init__(
        self,
        *,
        url: str,
        headers: Optional[dict[str, str]] = None,
        client: Any = None,
        timeout: float = 10.0,
    ):
        if not url:
            raise SiemError("WebhookSink requires url")
        self.url = url
        self.headers = headers or {}
        self._client = client
        self._timeout = timeout

    async def send(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        import httpx

        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.post(self.url, json={"events": events}, headers=self.headers)
        except httpx.HTTPError as exc:
            raise SiemError(f"webhook delivery failed: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        return {"sink": self.name, "sent": len(events), "status": resp.status_code,
                "ok": 200 <= resp.status_code < 300}


class ConsoleSink(SiemSink):
    """Olayları stdout'a yazar (yerel kullanım/tespit)."""

    name = "console"

    async def send(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        for event in events:
            print(json.dumps(event, ensure_ascii=False))
        return {"sink": self.name, "sent": len(events), "status": 0, "ok": True}


# ---------------------------------------------------------------------------
# Fabrika + orkestrasyon
# ---------------------------------------------------------------------------
def get_siem_sink() -> Optional[SiemSink]:
    """
    Env'e göre sink kurar. `MIRAGE_SIEM_SINK=none` (veya boş) ise None döner.
    `console` dışındaki sink'ler için `MIRAGE_SIEM_URL` zorunludur.
    """
    choice = (os.environ.get("MIRAGE_SIEM_SINK") or "none").strip().lower()
    if choice in ("", "none", "off"):
        return None
    if choice == "console":
        return ConsoleSink()

    url = (os.environ.get("MIRAGE_SIEM_URL") or "").strip()
    if not url:
        raise SiemError(f"MIRAGE_SIEM_URL required for sink {choice!r}")

    if choice == "hec":
        token = (os.environ.get("MIRAGE_SIEM_TOKEN") or "").strip()
        if not token:
            raise SiemError("MIRAGE_SIEM_TOKEN required for sink 'hec'")
        return HecSink(url=url, token=token, index=os.environ.get("MIRAGE_SIEM_INDEX") or None)

    if choice == "webhook":
        raw = os.environ.get("MIRAGE_SIEM_HEADERS")
        headers = json.loads(raw) if raw else None
        return WebhookSink(url=url, headers=headers)

    raise SiemError(f"unknown MIRAGE_SIEM_SINK: {choice!r}")


async def export_token(
    *,
    token: str,
    evidence_store: Any,
    triage_store: Any,
    sink: SiemSink,
) -> dict[str, Any]:
    """
    Bir token'ın kanıt + triyaj kayıtlarını toplar, olaylara çevirir ve sink'e
    gönderir. Kanıt zinciri önce doğrulanır (`chain_verified` olaylara işlenir).
    """
    evidence: list[dict[str, Any]] = []
    chain_verified: Optional[bool] = None
    if evidence_store is not None:
        evidence = evidence_store.list_chain(token)
        if evidence:
            chain_verified = evidence_store.verify(token).get("ok")

    triage: list[Any] = []
    if triage_store is not None:
        triage = triage_store.list_for_token(token)

    events = build_events(evidence=evidence, triage=triage, chain_verified=chain_verified)
    report = await sink.send(events) if events else {"sink": sink.name, "sent": 0,
                                                     "status": 0, "ok": True}
    return {
        "token": token,
        "chain_verified": chain_verified,
        "evidence_count": len(evidence),
        "triage_count": len(triage),
        "event_count": len(events),
        "delivery": report,
    }


__all__ = [
    "ConsoleSink",
    "HecSink",
    "SiemError",
    "SiemSink",
    "WebhookSink",
    "build_events",
    "export_token",
    "get_siem_sink",
]
