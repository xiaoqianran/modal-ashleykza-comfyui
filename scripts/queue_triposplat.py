#!/usr/bin/env python3
"""Deprecated. Use ``python3 -m workflow_queue --enable-glb``."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from workflow_queue import main  # noqa: E402

if __name__ == "__main__":
    extra = ["--enable-glb"]
    if "--workflow" not in sys.argv:
        extra.extend(["--workflow", "examples/triposplat-image-to-gaussian-splat.json"])
    if "--out" not in sys.argv:
        extra.extend(["--out", "artifacts/triposplat"])
    if "--no-glb" in sys.argv:
        extra = [item for item in extra if item != "--enable-glb"]
    main([*extra, *sys.argv[1:]])
