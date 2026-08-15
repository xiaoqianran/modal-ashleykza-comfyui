"""Shared process helpers for GPU start and Volume installs.

Looked up on ``comfy_engine`` so unit tests can keep patching
``comfy_engine._run`` / ``_comfy_python`` / ``_python_text``.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path


def _quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    display_cmd: list[str] | None = None,
) -> None:
    printable = " ".join(_quote(part) for part in (display_cmd or cmd))
    print(f"$ {printable}", flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def _comfy_python(comfy_root: Path) -> str:
    for name in ("python3", "python"):
        path = comfy_root / "venv" / "bin" / name
        if path.is_file():
            return str(path)
    return "python3"


def _module_import_error(name: str, python: str) -> str | None:
    try:
        result = subprocess.run(
            [python, "-c", f"import {name}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return str(exc)
    if result.returncode == 0:
        return None
    text = (result.stderr or result.stdout or "").strip()
    return text[-2000:] if text else f"exit {result.returncode}"


def _module_available(name: str, python: str) -> bool:
    return _module_import_error(name, python) is None


def _python_text(python: str, code: str) -> str:
    result = subprocess.run(
        [python, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"{python} -c produced no stdout")
    return lines[-1]


def _site_packages(python: str) -> Path | None:
    import comfy_engine

    try:
        text = comfy_engine._python_text(
            python, "import sysconfig; print(sysconfig.get_paths()['purelib'])"
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError, RuntimeError) as exc:
        print(f"[TRELLIS2] cannot locate site-packages ({exc})", flush=True)
        return None
    path = Path(text)
    if not path.is_dir():
        print(f"[TRELLIS2] site-packages is not a directory: {path}", flush=True)
        return None
    return path
