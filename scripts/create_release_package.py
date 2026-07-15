#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'mirage-release.zip'

EXCLUDE_DIRS = {
    '.git', '.next', '.vercel', '.venv', 'venv', 'node_modules', 'dist', 'build', 'out',
    '__pycache__', '.pytest_cache', 'coverage', 'downloads', 'download', '.zscripts',
}
EXCLUDE_FILES = {
    '.env', 'desktop.ini', 'dev.log', 'dev.out.log', 'server.log', 'memory.db', 'dev.db',
    'tsconfig.tsbuildinfo', 'mirage-release.zip',
}
EXCLUDE_PATTERNS = [
    '.env*', '*.pyc', '*.pyo', '*.log', '*.xlsx', '*.xlsm', '*.png', '*.jpg', '*.jpeg',
    '*.webp', '*.gif', '*.sqlite', '*.sqlite3', '*.db', '*.evidence.json',
]
ALLOW_FILES = {'.env.example'}


def is_excluded(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if any(part in EXCLUDE_DIRS for part in parts[:-1] if part):
        return True
    name = path.name
    if name in ALLOW_FILES:
        return False
    if name in EXCLUDE_FILES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDE_PATTERNS)


def iter_files() -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        current = Path(dirpath)
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for filename in filenames:
            path = current / filename
            if path == OUT:
                continue
            if not is_excluded(path):
                files.append(path)
    return sorted(files)


def main() -> None:
    files = iter_files()
    if OUT.exists():
        OUT.unlink()
    with ZipFile(OUT, 'w', ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(ROOT.parent).as_posix())
    print(f'created {OUT.name}')
    print(f'files: {len(files)}')
    print(f'size: {OUT.stat().st_size} bytes')


if __name__ == '__main__':
    main()
