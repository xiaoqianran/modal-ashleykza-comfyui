"""One file. First run unpacks the runtime into LocalAppData."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

CACHE_NAME = "ComfyStudio"
STAMP_NAME = "payload.stamp"


def meipass() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1] / "dist" / "payload"


def runtime_home() -> Path:
    override = os.environ.get("STUDIO_RUNTIME", "").strip()
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / CACHE_NAME


def layout(base: Path) -> tuple[Path, Path]:
    return base / "python" / "python.exe", base / "app"


def stamp_of(root: Path) -> str:
    path = root / STAMP_NAME
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def payload_ok(src: Path) -> bool:
    python, app = layout(src)
    return python.is_file() and (app / "studio").is_dir()


def ensure_runtime(src: Path, dest: Path) -> bool:
    python, app = layout(dest)
    wanted = stamp_of(src)
    have = stamp_of(dest)
    if python.is_file() and (app / "studio").is_dir() and wanted and wanted == have:
        return False
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    shutil.copytree(src / "python", dest / "python")
    shutil.copytree(src / "app", dest / "app")
    if wanted:
        (dest / STAMP_NAME).write_text(wanted + "\n", encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    src = meipass()
    if not payload_ok(src):
        print("这个 Studio.exe 不完整。请重新下载这一个文件，不要再解一堆目录。", file=sys.stderr)
        return 1
    dest = runtime_home() / "runtime"
    try:
        copied = ensure_runtime(src, dest)
    except OSError as exc:
        print(f"释放运行时失败：{exc}", file=sys.stderr)
        return 1
    if copied:
        print(f"已写入 {dest}（以后双击这一个 exe 即可，不用再带别的文件）", flush=True)
    python, app = layout(dest)
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
