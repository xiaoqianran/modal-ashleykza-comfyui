"""Install Python packages in the Ashley venv with uv, not pip / pipx.

The GPU Image bakes a static musl ``uv`` + ``uvx`` into ``/usr/local/bin`` and
symlinks them into the Ashley venv. Runtime helpers resolve that binary and
build:

- ``uv pip install --python <venv>`` for packages that must land in Ashley's venv
- ``uvx`` for one-off CLI tools (the pipx replacement)

Hydrate already uses Modal's ``Image.uv_pip_install``. This module is for the
ComfyUI venv inside the Ashley registry image, which Modal's helper does not
target.
"""

from __future__ import annotations

import shlex
import shutil
import tarfile
import tempfile
import urllib.request
from collections.abc import Sequence
from pathlib import Path

UV_VERSION = "0.12.4"
UV_LINUX_X64_URL = (
    f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/"
    "uv-x86_64-unknown-linux-musl.tar.gz"
)
IMAGE_UV = "/usr/local/bin/uv"
IMAGE_UVX = "/usr/local/bin/uvx"
VENV_UV = "/ComfyUI/venv/bin/uv"
VENV_UVX = "/ComfyUI/venv/bin/uvx"


def _first_existing(*candidates: str | Path | None) -> str | None:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return str(path)
    return None


def resolve_uv() -> str:
    """Prefer the Image binary, then the venv symlink, then PATH."""
    return _first_existing(IMAGE_UV, VENV_UV, shutil.which("uv")) or "uv"


def resolve_uvx() -> str:
    return _first_existing(IMAGE_UVX, VENV_UVX, shutil.which("uvx")) or "uvx"


def pip_install_cmd(
    python: str,
    *args: str,
    site_dir: str | Path | None = None,
    uv: str | None = None,
) -> list[str]:
    """``uv pip install --python <venv> --no-cache`` (+ optional ``--target``)."""
    cmd = [uv or resolve_uv(), "pip", "install", "--python", python, "--no-cache"]
    if site_dir is not None:
        cmd.extend(["--target", str(site_dir)])
    cmd.extend(args)
    return cmd


def pip_uninstall_cmd(
    python: str,
    *packages: str,
    uv: str | None = None,
) -> list[str]:
    return [uv or resolve_uv(), "pip", "uninstall", "--python", python, "-y", *packages]


def uvx_cmd(*args: str, uvx: str | None = None) -> list[str]:
    """One-off tool runner. This is the uv stand-in for pipx."""
    return [uvx or resolve_uvx(), *args]


def is_uv_pip_cmd(cmd: Sequence[str]) -> bool:
    return (
        len(cmd) >= 3
        and Path(cmd[0]).name == "uv"
        and cmd[1] == "pip"
        and cmd[2] == "install"
        and "--python" in cmd
    )


def shell_resolve_uv() -> str:
    """POSIX snippet that sets ``$UV`` without printing the token."""
    return (
        f'UV={shlex.quote(IMAGE_UV)}; '
        f'[ -x "$UV" ] || UV={shlex.quote(VENV_UV)}; '
        '[ -x "$UV" ] || UV=uv'
    )


def image_install_uv_command() -> str:
    """One Image RUN: download musl uv+uvx into ``/usr/local/bin`` (no pip)."""
    return (
        "set -eux; "
        f"curl -fsSL {shlex.quote(UV_LINUX_X64_URL)} -o /tmp/uv.tgz; "
        "mkdir -p /tmp/uv-extract /usr/local/bin /ComfyUI/venv/bin; "
        "tar -xzf /tmp/uv.tgz -C /tmp/uv-extract; "
        'UV_BIN=$(find /tmp/uv-extract -type f -name uv | head -n 1); '
        'UVX_BIN=$(find /tmp/uv-extract -type f -name uvx | head -n 1); '
        'test -n "$UV_BIN" && test -n "$UVX_BIN"; '
        'install -m 0755 "$UV_BIN" /usr/local/bin/uv; '
        'install -m 0755 "$UVX_BIN" /usr/local/bin/uvx; '
        "ln -sfn /usr/local/bin/uv /ComfyUI/venv/bin/uv; "
        "ln -sfn /usr/local/bin/uvx /ComfyUI/venv/bin/uvx; "
        "rm -rf /tmp/uv.tgz /tmp/uv-extract; "
        "/usr/local/bin/uv --version"
    )


def image_uv_pip_command(
    python: str,
    *packages: str,
    upgrade: bool = False,
) -> str:
    pkgs = " ".join(shlex.quote(package) for package in packages)
    flag = " -U" if upgrade else ""
    return (
        "set -eux; "
        f"{IMAGE_UV} pip install --python {shlex.quote(python)} --no-cache{flag} {pkgs}"
    )


def image_uv_uninstall_command(python: str, *packages: str) -> str:
    pkgs = " ".join(shlex.quote(package) for package in packages)
    return (
        f"{IMAGE_UV} pip uninstall --python {shlex.quote(python)} -y {pkgs} || true"
    )


def _extract_uv_members(archive: Path, dest: Path) -> tuple[Path, Path]:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest, filter="data")
    uv_matches = sorted(path for path in dest.rglob("uv") if path.is_file())
    uvx_matches = sorted(path for path in dest.rglob("uvx") if path.is_file())
    if not uv_matches or not uvx_matches:
        raise RuntimeError(f"uv tarball missing uv/uvx under {dest}")
    return uv_matches[0], uvx_matches[0]


def install_uv_tarball(dest_dir: str | Path, *, url: str = UV_LINUX_X64_URL) -> Path:
    """Unpack the musl uv+uvx build into ``dest_dir`` and return the uv path."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "uv.tgz"
        extract = Path(directory) / "extract"
        with urllib.request.urlopen(url, timeout=120) as response:
            archive.write_bytes(response.read())
        if archive.read_bytes()[:2] != b"\x1f\x8b":
            raise RuntimeError(f"uv download was not a gzip tarball: {url}")
        uv_src, uvx_src = _extract_uv_members(archive, extract)
        uv_dest = dest_dir / "uv"
        uvx_dest = dest_dir / "uvx"
        shutil.copy2(uv_src, uv_dest)
        shutil.copy2(uvx_src, uvx_dest)
        uv_dest.chmod(0o755)
        uvx_dest.chmod(0o755)
    return uv_dest
