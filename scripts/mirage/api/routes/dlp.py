"""
MIRAGE API — Regex ötesi DLP ucu.

`POST /dlp/scan` — metni checksum (TCKN/IBAN/Luhn) + entropi (JWT/yüksek
entropi sır) + gazetteer/bağlam (ad/adres) + müşteri regex kurallarından geçirir.
Yanıt: `{"findings": [...], "summary": {...}}`.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..deps import require_api_token
from ...dlp import DLPScanner, summarize

router = APIRouter(prefix="/dlp", tags=["dlp"])


class DLPRuleModel(BaseModel):
    name: str = Field(..., description="Rule name")
    pattern: str = Field(..., description="Regex")
    severity: str = Field("low", pattern="^(low|medium|high|critical)$")
    description: str = Field("")


class DLPSecretModel(BaseModel):
    name: str = Field(..., description="Field name (e.g. 'api_key')")
    value: str = Field(..., description="Field value to inspect")


class DLPScanRequest(BaseModel):
    text: str = Field(..., description="Text to scan")
    rules: list[DLPRuleModel] = Field(default_factory=list, description="Customer regex rules")
    secrets: Optional[list[DLPSecretModel]] = Field(
        None, description="Optional structured fields to scan individually"
    )


@router.post("/scan")
def scan_text(req: DLPScanRequest, request: Request) -> dict:
    """
    Bulguları ve özeti döner. `secrets` verilirse her alan ayrı taranır ve
    bulguların `detail` alanına alan adı işlenir.
    """
    require_api_token(request)
    scanner = DLPScanner(rules=[r.model_dump() for r in req.rules])
    try:
        findings = scanner.scan(req.text)
        if req.secrets:
            for field in req.secrets:
                for f in scanner.scan(field.value):
                    findings.append(
                        replace(f, detail=f"{field.name}: {f.detail}".strip(": "))
                    )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DLP error: {exc}")
    return {
        "findings": [f.to_dict() for f in findings],
        "summary": summarize(findings),
    }
