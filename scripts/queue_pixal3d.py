#!/usr/bin/env python3
"""Deprecated. Use ``python3 -m workflow_queue``."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from workflow_queue import main  # noqa: E402

if __name__ == "__main__":
    extra: list[str] = []
    if "--workflow" not in sys.argv:
        extra.extend(["--workflow", "examples/pixal3d-image-to-3d.json"])
    if "--out" not in sys.argv:
        extra.extend(["--out", "artifacts/pixal3d"])
    main([*extra, *sys.argv[1:]])
