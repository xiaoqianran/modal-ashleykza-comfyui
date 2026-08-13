#!/usr/bin/env python3
"""Generic queue helper. Prefer ``python3 -m workflow_queue``."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from workflow_queue import main  # noqa: E402

if __name__ == "__main__":
    main()
