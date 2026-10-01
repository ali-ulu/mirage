"""
MIRAGE — Prompt red-team / CI tarayıcısı.

Depodaki prompt taşıyan dosyaları (sistem promptları, ajan talimatları, RAG
şablonları) **yayına girmeden** prompt-injection, jailbreak, sızdırma
talimatları ve gizli Unicode (bidi/zero-width) için tarar. Bir CI kapısı olarak
kullanılır: bulgu eşik üstündeyse süreç sıfırdan farklı kodla çıkar.

Tasarım:
  - `Rule` dataclass + `DEFAULT_RULES`: saf, deterministik, LLM gerekmez.
  - `scan_text`: regex + gizli Unicode + canary (tek kaynak: `agent/prompt_canary`).
  - `scan_files`: dosya/dizin ağacı üzerinde toplar; ikili/büyük dosyalar atlanır.
  - Bozuk regex fail-safe atlanır; çekirdek bozulmaz.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Optional

from .agent.prompt_canary import detect_canaries

_SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}

# Gizli/kontrol Unicode karakterleri: bidi override + zero-width.
_HIDDEN_UNICODE = {
    "\u202a": "LEFT-TO-RIGHT EMBEDDING",
    "\u202b": "RIGHT-TO-LEFT EMBEDDING",
    "\u202c": "POP DIRECTIONAL FORMATTING",
    "\u202d": "LEFT-TO-RIGHT OVERRIDE",
    "\u202e": "RIGHT-TO-LEFT OVERRIDE",
    "\u2066": "LEFT-TO-RIGHT ISOLATE",
    "\u2067": "RIGHT-TO-LEFT ISOLATE",
    "\u2068": "FIRST STRONG ISOLATE",
    "\u2069": "POP DIRECTIONAL ISOLATE",
    "\u200b": "ZERO WIDTH SPACE",
    "\u200c": "ZERO WIDTH NON-JOINER",
    "\u200d": "ZERO WIDTH JOINER",
    "\ufeff": "ZERO WIDTH NO-BREAK SPACE",
}

# Varsayılan metin dosyası uzantıları — prompt ARTEFAKTLARI (kod değil).
# Kod dosyaları güvenlik kuralı metinlerini meşru biçimde içerdiği için
# varsayılanda taranmaz; gerektiğinde `include_suffixes` ile eklenir.
_TEXT_SUFFIXES = frozenset({
    ".md", ".txt", ".prompt", ".tmpl", ".jinja", ".jinja2", ".mustache",
    ".json", ".yaml", ".yml", ".toml",
})

_MAX_BYTES = 512 * 1024


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: str
    severity: str
    description: str


DEFAULT_RULES: tuple[Rule, ...] = (
    Rule(
        "ignore_instructions",
        r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)\s+instructions",
        "high",
        "Önceki talimatları yok sayma girişimi (klasik prompt injection)",
    ),
    Rule(
        "disregard_instructions",
        r"disregard\s+(all\s+)?(the\s+)?(previous|prior|above|earlier|system)",
        "high",
        "Talimatları geçersiz kılma girişimi",
    ),
    Rule(
        "reveal_system_prompt",
        r"(reveal|show|print|repeat|output)\s+(me\s+)?(your|the)\s+"
        r"(system\s+)?(prompt|instructions|rules|guidelines)",
        "high",
        "Sistem promptunu ifşa etme talebi",
    ),
    Rule(
        "exfiltrate_data",
        r"(send|post|upload|exfiltrate|forward|email|curl|leak|share)\s+"
        r"(the\s+|all\s+|your\s+|these\s+|this\s+|our\s+)?"
        r"(data|dump|keys?|secrets?|credentials?|passwords?|records?|files?|tokens?|"
        r"database|db|source)\b.{0,80}?(https?://|[\w.+-]+@[\w-]+\.[\w.-]+)",
        "critical",
        "Veriyi dışarı sızdırma (URL/e-posta) talimatı",
    ),
    Rule(
        "role_hijack",
        r"(you\s+are\s+now|act\s+as\s+(a\s+)?(different|new|unrestricted)|pretend\s+to\s+be|from\s+now\s+on\s+you)",
        "medium",
        "Rol/kişilik ele geçirme (role hijack)",
    ),
    Rule(
        "jailbreak",
        r"(developer\s+mode|do\s+anything\s+now|\bDAN\s+mode\b|jailbreak|no\s+restrictions\s+mode)",
        "high",
        "Jailbreak kalıbı",
    ),
    Rule(
        "override_guardrails",
        r"(override|bypass|disable|turn\s+off)\s+(the\s+)?(safety|security|guardrails?|polic(y|ies)|filters?|restrictions?)",
        "high",
        "Güvenlik korumalarını devre dışı bırakma girişimi",
    ),
    Rule(
        "tool_abuse",
        r"(execute|run|eval)\s+(this\s+)?(shell\s+)?(command|code|script)",
        "medium",
        "Araç/kabuk kötüye kullanım talimatı",
    ),
)


def _iter_hidden_unicode(text: str) -> Iterable[tuple[str, int]]:
    for idx, ch in enumerate(text):
        if ch in _HIDDEN_UNICODE:
            yield _HIDDEN_UNICODE[ch], idx


def scan_text(text: str, *, rules: Optional[Iterable[Rule]] = None) -> list[dict[str, Any]]:
    """
    Metni prompt-injection kuralları, gizli Unicode ve canary için tarar.

    Döndürür: her bulgu için `{"rule", "severity", "match", "offset", "description"}`.
    """
    findings: list[dict[str, Any]] = []
    active_rules = tuple(rules) if rules is not None else DEFAULT_RULES

    for rule in active_rules:
        try:
            pattern = re.compile(rule.pattern, re.IGNORECASE | re.DOTALL)
        except re.error:
            continue  # bozuk müşteri kuralı fail-safe atlanır
        match = pattern.search(text)
        if match:
            findings.append({
                "rule": rule.name,
                "severity": rule.severity,
                "match": match.group(0)[:120],
                "offset": match.start(),
                "description": rule.description,
            })

    for name, offset in _iter_hidden_unicode(text):
        findings.append({
            "rule": "hidden_unicode",
            "severity": "high",
            "match": name,
            "offset": offset,
            "description": f"Gizli Unicode karakteri: {name}",
        })

    for token in detect_canaries(text):
        findings.append({
            "rule": "canary_leak",
            "severity": "critical",
            "match": token,
            "offset": text.find(token),
            "description": "Gömülü prompt canary token'ı metinde açıkta",
        })

    return findings


def max_severity(findings: list[dict[str, Any]]) -> Optional[str]:
    """Bulgu kümesindeki en yüksek şiddet; boşsa None."""
    if not findings:
        return None
    return max((f["severity"] for f in findings), key=lambda s: _SEVERITY_ORDER.get(s, 0))


def exceeds(findings: list[dict[str, Any]], threshold: str) -> bool:
    """Bulgu şiddeti eşiği aşıyor mu (threshold dahil)?"""
    top = max_severity(findings)
    if top is None:
        return False
    return _SEVERITY_ORDER.get(top, 0) >= _SEVERITY_ORDER.get(threshold, 99)


def _is_candidate(path: Path, extra_suffixes: frozenset[str]) -> bool:
    if path.suffix.lower() in _TEXT_SUFFIXES or path.suffix.lower() in extra_suffixes:
        return True
    return path.name in {"AGENTS.md", "CLAUDE.md", "prompt.txt"}


def scan_files(
    paths: Iterable[str | Path],
    *,
    rules: Optional[Iterable[Rule]] = None,
    exclude: Optional[Iterable[str]] = None,
    include_suffixes: Optional[Iterable[str]] = None,
) -> list[dict[str, Any]]:
    """
    Dosya/dizin ağacını tarar. İkili ve >512 KiB dosyalar atlanır.

    `exclude`: `fnmatch` glob kalıpları (ör. `*test_*`, `*/fixtures/*`).

    Döndürür: `{"path", "findings"}` kayıtları (yalnızca bulgu olan dosyalar).
    """
    from fnmatch import fnmatch

    patterns = tuple(exclude or ())
    extra = frozenset(s.lower() for s in (include_suffixes or ()))
    results: list[dict[str, Any]] = []
    for raw in paths:
        base = Path(raw)
        candidates = [base] if base.is_file() else sorted(base.rglob("*"))
        for path in candidates:
            if not path.is_file() or not _is_candidate(path, extra):
                continue
            if patterns and any(
                fnmatch(path.name, p) or fnmatch(str(path), p) for p in patterns
            ):
                continue
            try:
                if path.stat().st_size > _MAX_BYTES:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # ikili/okunamayan dosya atlanır
            findings = scan_text(text, rules=rules)
            if findings:
                results.append({"path": str(path), "findings": findings})
    return results


def _main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    as_json = "--json" in argv
    threshold = "high"
    exclude: list[str] = []
    include: list[str] = []
    for arg in argv:
        if arg.startswith("--fail-on="):
            threshold = arg.split("=", 1)[1]
        elif arg.startswith("--exclude="):
            exclude.append(arg.split("=", 1)[1])
        elif arg.startswith("--include="):
            include.append(arg.split("=", 1)[1])

    if not args:
        print(
            "usage: python -m mirage.redteam <path...> [--json] "
            "[--fail-on=high] [--exclude=GLOB] [--include=SUFFIX]",
            file=sys.stderr,
        )
        return 2

    results = scan_files(args, exclude=exclude, include_suffixes=include)
    total = sum(len(r["findings"]) for r in results)
    worst = max((max_severity(r["findings"]) for r in results), key=lambda s: _SEVERITY_ORDER.get(s or "", 0), default=None)
    gated = any(exceeds(r["findings"], threshold) for r in results)

    if as_json:
        print(json.dumps({"files": results, "total": total, "max_severity": worst,
                          "threshold": threshold, "failed": gated}, ensure_ascii=False))
    else:
        for record in results:
            print(f"{record['path']}:")
            for f in record["findings"]:
                print(f"  [{f['severity']}] {f['rule']} @{f['offset']}: {f['description']}")
        print(f"\n{total} bulgu, {len(results)} dosya; en yüksek: {worst or '-'}; eşik: {threshold}")
    return 1 if gated else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))


__all__ = [
    "DEFAULT_RULES",
    "Rule",
    "exceeds",
    "max_severity",
    "scan_files",
    "scan_text",
]
