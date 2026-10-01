"""`python -m mirage <path...>` → prompt red-team tarayıcısı."""
from __future__ import annotations

import sys

from .redteam import _main

if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
