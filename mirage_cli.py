#!/usr/bin/env python3
"""MIRAGE Decoy Generator CLI.

Generates realistic finance/HR decoy datasets, writes a passive-only honeytoken
XLSX, and emits machine-readable evidence for demo and QA runs.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd

# Support both root directory and scripts directory executions.
SCRIPT_DIR = Path(__file__).resolve().parent
for p in (str(SCRIPT_DIR), str(SCRIPT_DIR / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from mirage import MirageSynthesizer  # noqa: E402
from mirage.honeytoken import MIRAGE_FORBIDDEN_PATTERNS, inject_honeytoken  # noqa: E402

DEFAULT_BASE_URL = "https://api.mirage.local/track"
MAX_ROWS = 100_000
DEFAULT_SEED_ROWS = 750
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_http_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise argparse.ArgumentTypeError("--base-url must be an absolute http(s) URL")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise argparse.ArgumentTypeError("--base-url must use HTTPS outside localhost demos")
    return value.rstrip("/")


def _validate_uuid_token(value: str) -> str:
    if not UUID_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "--token must be a UUID because the beacon receiver validates UUID tokens. "
            "Use --label for human-readable demo names."
        )
    return str(uuid.UUID(value))


def _positive_rows(value: str) -> int:
    try:
        rows = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--rows must be an integer") from exc
    if rows <= 0:
        raise argparse.ArgumentTypeError("--rows must be greater than zero")
    if rows > MAX_ROWS:
        raise argparse.ArgumentTypeError(f"--rows cannot exceed {MAX_ROWS:,}")
    return rows


def _build_finance_seed(n: int = DEFAULT_SEED_ROWS, seed: int = 17) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    tx_types = np.array(["TRANSFER", "SWIFT", "ATM_WITHDRAWAL", "INVESTMENT", "LOAN_DISBURSEMENT", "CARD_SETTLEMENT"])
    type_probs = np.array([0.38, 0.10, 0.18, 0.14, 0.08, 0.12])
    currencies = np.array(["TRY", "USD", "EUR", "GBP"])
    currency_probs = np.array([0.68, 0.17, 0.12, 0.03])

    transaction_type = rng.choice(tx_types, size=n, p=type_probs)
    currency = rng.choice(currencies, size=n, p=currency_probs)

    base_amount = rng.lognormal(mean=10.0, sigma=1.05, size=n)
    multipliers = np.where(transaction_type == "SWIFT", 4.0, 1.0)
    multipliers = np.where(transaction_type == "LOAN_DISBURSEMENT", 5.5, multipliers)
    multipliers = np.where(transaction_type == "ATM_WITHDRAWAL", 0.08, multipliers)
    amount = np.clip(base_amount * multipliers, 50, 4_500_000).round(2)

    normalized_amount = np.clip(np.log10(amount + 1) / 7.0, 0, 1)
    type_risk = np.select(
        [
            transaction_type == "SWIFT",
            transaction_type == "LOAN_DISBURSEMENT",
            transaction_type == "INVESTMENT",
            transaction_type == "ATM_WITHDRAWAL",
        ],
        [0.28, 0.20, 0.12, -0.08],
        default=0.02,
    )
    risk_score = np.clip(normalized_amount + type_risk + rng.normal(0, 0.06, size=n), 0.01, 0.99).round(3)

    iban_suffix = rng.integers(10**15, 10**16 - 1, size=n)
    account_numbers = [f"TR{rng.integers(10, 99):02d}0001000{suffix}"[:26] for suffix in iban_suffix]

    started = pd.Timestamp("2026-01-01T00:00:00Z")
    timestamps = started + pd.to_timedelta(rng.integers(0, 180 * 24 * 3600, size=n), unit="s")

    return pd.DataFrame(
        {
            "transaction_id": [f"TXN-{100000 + i}" for i in range(n)],
            "account_number": account_numbers,
            "amount": amount,
            "currency": currency,
            "type": transaction_type,
            "risk_score": risk_score,
            "branch_code": rng.choice(["IST-01", "ANK-02", "IZM-03", "LON-01", "FRA-02"], size=n),
            "created_at": timestamps.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )


def _build_hr_seed(n: int = DEFAULT_SEED_ROWS, seed: int = 29) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    departments = np.array(["ENGINEERING", "REVENUE", "FINANCE", "HUMAN_RESOURCES", "LEGAL", "MARKETING", "OPERATIONS"])
    dept_probs = np.array([0.31, 0.21, 0.12, 0.09, 0.07, 0.10, 0.10])
    department = rng.choice(departments, size=n, p=dept_probs)

    dept_salary_base = {
        "ENGINEERING": 128_000,
        "REVENUE": 92_000,
        "FINANCE": 105_000,
        "HUMAN_RESOURCES": 78_000,
        "LEGAL": 118_000,
        "MARKETING": 84_000,
        "OPERATIONS": 74_000,
    }
    seniority = rng.integers(1, 16, size=n)
    perf_score = np.clip(2.4 + seniority * 0.12 + rng.normal(0, 0.45, size=n), 1.0, 5.0).round(2)
    salary = np.array([dept_salary_base[d] for d in department], dtype=float)
    salary = (salary + seniority * rng.normal(5200, 900, size=n) + perf_score * 4200 + rng.normal(0, 8500, size=n))
    salary = np.clip(salary, 42_000, 320_000).round(2)

    first_names = np.array(["Ada", "Deniz", "Ekin", "Mert", "Selin", "Baran", "Lara", "Efe", "Mina", "Arda"])
    last_names = np.array(["Aydin", "Kaya", "Demir", "Yildiz", "Arslan", "Sahin", "Ozer", "Polat", "Eren", "Koc"])
    names = [f"{rng.choice(first_names)} {rng.choice(last_names)}" for _ in range(n)]

    hired = pd.Timestamp("2019-01-01T00:00:00Z") + pd.to_timedelta(rng.integers(0, 7 * 365, size=n), unit="D")
    return pd.DataFrame(
        {
            "employee_id": [f"EMP-{10_000 + i}" for i in range(n)],
            "full_name": names,
            "email": [f"employee{i:05d}@corp.example" for i in range(n)],
            "department": department,
            "salary": salary,
            "perf_score": perf_score,
            "seniority_years": seniority,
            "hired_at": hired.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )


def _build_seed(vertical: str, seed: int) -> pd.DataFrame:
    if vertical == "finance":
        return _build_finance_seed(seed=seed)
    if vertical == "hr":
        return _build_hr_seed(seed=seed)
    raise ValueError(f"unsupported vertical: {vertical}")


def _find_external_relationship(xlsx_bytes: bytes, base_url: str) -> tuple[str, str]:
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes), "r") as zf:
        for member in zf.namelist():
            if not member.endswith(".rels"):
                continue
            text = zf.read(member).decode("utf-8", errors="ignore")
            if base_url in text and 'TargetMode="External"' in text:
                target_match = re.search(r'Target="([^"]+)"', text)
                return member, target_match.group(1) if target_match else ""
    raise RuntimeError("passive external relationship was not found in generated XLSX")


def _verify_passive_only(xlsx_bytes: bytes, base_url: str) -> dict[str, Any]:
    forbidden_hits: list[dict[str, str]] = []
    members: list[str] = []
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes), "r") as zf:
        members = zf.namelist()
        banned_members = [m for m in members if any(part in m for part in ("vbaProject.bin", "oleObject", "macrosheets"))]
        for member in members:
            content = zf.read(member)
            try:
                text = content.decode("utf-8", errors="ignore")
            except UnicodeDecodeError:
                continue
            lower = text.lower()
            for pattern in MIRAGE_FORBIDDEN_PATTERNS:
                if pattern.lower() in lower:
                    forbidden_hits.append({"member": member, "pattern": pattern})
    rel_member, target = _find_external_relationship(xlsx_bytes, base_url)
    if banned_members:
        raise RuntimeError(f"active Office payload members found: {banned_members}")
    if forbidden_hits:
        raise RuntimeError(f"forbidden payload patterns found: {forbidden_hits}")
    return {
        "passive_only": True,
        "zip_members": len(members),
        "external_relationship_member": rel_member,
        "external_relationship_target": target,
        "active_payload_members": [],
        "forbidden_pattern_hits": [],
    }


def _write_registry_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    else:
        current = {"version": 1, "records": []}
    current.setdefault("records", []).append(record)
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MIRAGE // Hardened Decoy & Honeytoken Dataset Generator CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--vertical", choices=["finance", "hr"], required=True, help="Decoy template vertical")
    parser.add_argument("--rows", type=_positive_rows, default=1000, help="Synthetic row count")
    parser.add_argument("--token", type=_validate_uuid_token, default=None, help="Optional UUID honeytoken")
    parser.add_argument("--label", default="", help="Human-readable demo label; not used as beacon token")
    parser.add_argument("--out", required=True, help="Output XLSX path")
    parser.add_argument("--base-url", type=_validate_http_base_url, default=DEFAULT_BASE_URL, help="Beacon base URL, usually ending in /track")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic generation seed")
    parser.add_argument("--registry-json", default=None, help="Optional JSON registry file to append token metadata")
    parser.add_argument("--evidence-json", default=None, help="Optional evidence JSON output path")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    token = args.token or str(uuid.uuid4())
    out_path = Path(args.out)
    label = args.label or f"{args.vertical}-decoy-{datetime.now(timezone.utc).strftime('%Y%m%d')}"

    print(f"[*] MIRAGE CLI started | vertical={args.vertical.upper()} rows={args.rows:,}")
    print(f"[*] Token UUID: {token}")
    print(f"[*] Demo label: {label}")

    seed_df = _build_seed(args.vertical, args.seed)
    print(f"[*] Seed profile rows: {len(seed_df):,} | columns: {', '.join(seed_df.columns)}")

    try:
        engine = MirageSynthesizer(seed=args.seed).fit(seed_df)
        result = engine.synthesize(args.rows)
        synthetic_df = result.df
    except Exception as exc:
        print(f"[!] Synthesis failed: {exc}", file=sys.stderr)
        return 1

    print(f"[*] Synthetic generation: {result.elapsed_ms:.2f} ms | {result.ms_per_row:.5f} ms/row")

    try:
        xlsx_bytes = inject_honeytoken(synthetic_df, base_url=args.base_url, sheet_name="DecoyData", token=token)
        passive_evidence = _verify_passive_only(xlsx_bytes, args.base_url)
    except Exception as exc:
        print(f"[!] Honeytoken injection or passive-only verification failed: {exc}", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(xlsx_bytes)
    file_sha256 = hashlib.sha256(xlsx_bytes).hexdigest()

    full_url = f"{args.base_url.rstrip('/')}/{token}"
    registry_record = {
        "token": token,
        "base_url": args.base_url.rstrip("/"),
        "full_url": full_url,
        "label": label,
        "vertical": args.vertical,
        "row_count": len(synthetic_df),
        "columns": list(synthetic_df.columns),
        "created_at": _utc_now(),
        "file_name": out_path.name,
        "file_sha256": file_sha256,
        "file_size_bytes": len(xlsx_bytes),
    }

    if args.registry_json:
        _write_registry_record(Path(args.registry_json), registry_record)
        print(f"[*] Registry updated: {args.registry_json}")

    evidence = {
        "ok": True,
        "generator": "MIRAGE Decoy Generator CLI",
        "vertical": args.vertical,
        "rows": len(synthetic_df),
        "token": token,
        "label": label,
        "output_path": str(out_path),
        "file_sha256": file_sha256,
        "file_size_bytes": len(xlsx_bytes),
        "tracking_url": full_url,
        "synthesis": {
            "elapsed_ms": round(result.elapsed_ms, 3),
            "ms_per_row": round(result.ms_per_row, 6),
        },
        "passive_ooxml_evidence": passive_evidence,
    }

    if args.evidence_json:
        evidence_path = Path(args.evidence_json)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[*] Evidence written: {args.evidence_json}")

    print(f"[+] SUCCESS: decoy XLSX written -> {out_path}")
    print(f"[+] Tracking URL: {full_url}")
    print(f"[+] SHA256: {file_sha256}")
    print(f"[+] Passive OOXML relationship: {passive_evidence['external_relationship_member']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
