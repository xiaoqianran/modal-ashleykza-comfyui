"""Double-click entry. Starts the bundled python -m studio."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1] / "dist" / "Studio"


def layout(base: Path) -> tuple[Path, Path]:
    return base / "python" / "python.exe", base / "app"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    python, app = layout(bundle_root())
    if not python.is_file():
        print(f"找不到内置 Python：{python}", file=sys.stderr)
        print("请解压完整的 Studio-windows.zip，再双击 Studio.exe。", file=sys.stderr)
        return 1
    if not (app / "studio").is_dir():
        print(f"找不到 app/studio：{app}", file=sys.stderr)
        return 1
    env = os.environ.copy()
    env["PYTHONPATH"] = str(app) + os.pathsep + env.get("PYTHONPATH", "")
    env["PATH"] = os.pathsep.join(
        [str(python.parent), str(python.parent / "Scripts"), env.get("PATH", "")]
    )
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        return subprocess.call([str(python), "-m", "studio", *args], cwd=str(app), env=env)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
