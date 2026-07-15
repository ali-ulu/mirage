#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = ROOT / 'mirage-release.zip'
FORBIDDEN = [
    re.compile(r'(^|/)\.git(/|$)'),
    re.compile(r'(^|/)node_modules(/|$)'),
    re.compile(r'(^|/)\.next(/|$)'),
    re.compile(r'(^|/)\.vercel(/|$)'),
    re.compile(r'(^|/)\.venv(/|$)'),
    re.compile(r'(^|/)venv(/|$)'),
    re.compile(r'(^|/)downloads?(/|$)'),
    re.compile(r'(^|/)\.pytest_cache(/|$)'),
    re.compile(r'(^|/)desktop\.ini$', re.I),
    re.compile(r'\.env$', re.I),
    re.compile(r'\.log$', re.I),
    re.compile(r'\.(xlsx|xlsm|png|jpg|jpeg|webp|gif)$', re.I),
    re.compile(r'\.evidence\.json$', re.I),
]


def main() -> None:
    if not ZIP_PATH.exists():
        raise SystemExit(f'missing {ZIP_PATH}')
    with ZipFile(ZIP_PATH) as zf:
        names = sorted(zf.namelist())
    hits = [name for name in names if any(pattern.search(name) for pattern in FORBIDDEN)]
    print(f'zip: {ZIP_PATH.name}')
    print(f'files: {len(names)}')
    if hits:
        print('FORBIDDEN ARTIFACTS:')
        for hit in hits:
            print(hit)
        raise SystemExit(1)
    print('forbidden artifact check: clean')


if __name__ == '__main__':
    main()
