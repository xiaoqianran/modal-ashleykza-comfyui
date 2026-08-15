"""Pinned comfy-env isolation protocol.

``comfy-env`` is not a pip helper. It is the host-side library that finds a
pixi workspace and RPCs node ``execute()`` into that env. pytorch3d / gsplat /
nvdiffrast live **only** in the pixi env. If discovery fails, the same node
classes import in the host ComfyUI process and die on ``No module named
'pytorch3d'``.

0.3.x and 0.4+ are different protocols (workspace layout), not a semver bump:

* 0.3.89 (what ``ComfyUI-SAM3DObjects`` pins): ``<root>/.pixi/envs/<name>/``
* 0.4+: ``<root>/envs/<name>/.pixi/envs/default/`` — **no** backward compat

This module is the only place that may change when bumping the pin.
Do not ``uv pip install comfy-env`` unpinned. Do not follow PyPI latest.
Bump only after rematerializing the pixi workspace and re-smoking on L40S.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

PACKAGE = "comfy-env"
VERSION = "0.3.89"
PIN = f"{PACKAGE}=={VERSION}"
ROOT_VAR = "COMFY_ENV_ROOT"
SITE_MARK = PACKAGE
SKIP_PACKAGES = frozenset({PACKAGE})

# 0.3.89 wrap._find_env_dir / get_workspace_env_dir
V03_PYTHON_GLOB = ".pixi/envs/*/bin/python"
# 0.4+ only — invisible to 0.3 wrap unless bridged
V04_PYTHON_GLOB = "envs/*/.pixi/envs/default/bin/python"

# 0.3.x accepts the worker socket, then waits a hardcoded 60s for ready.
# First ``import torch`` on a cold Volume is slower than that.
READY_TIMEOUT_SECONDS = 600
WORKER_LOG = "/workspace/logs/sam3d-isolation-worker.log"

# Stock 0.3.89 isolation source, or the already-patched form.
# If a future yank of 0.3.89 changes these, boot must fail — do not no-op.
READY_RECV_STOCK = "msg = self._transport.recv(timeout=60)"
READY_RECV_OURS = f"msg = self._transport.recv(timeout={READY_TIMEOUT_SECONDS})"
STDOUT_STOCK = "stdout=subprocess.DEVNULL,"
STDOUT_OURS = f"stdout=open({WORKER_LOG!r}, \"ab\"),"
PIXI_RUN_STOCK = 'PIXI, "run", "--as-is",'
PIXI_RUN_OURS = 'PIXI, "run", "--as-is", "--frozen",'
IS_PIXI_STOCK_RE = re.compile(r"is_pixi = ['\"]\.pixi['\"] in str\(self\.python\)")
IS_PIXI_OURS = "is_pixi = False"
SOCKET_TIMEOUT_RE = re.compile(r"^(SOCKET_ACCEPT_TIMEOUT\s*=\s*)\d+", re.M)
WRAP_SP_STOCK = (
    '        matches = glob.glob(str(env_dir / "lib/python*/site-packages"))\n'
    "        sp = Path(matches[0]) if matches else None"
)
WRAP_SP_OURS = (
    '        matches = glob.glob(str(env_dir / "lib/python*/site-packages"))\n'
    "        matches.sort(key=lambda p: tuple("
    "int(x) if str(x).isdigit() else 0 "
    "for x in Path(p).parent.name.replace('python', '', 1).split('.')), reverse=True)\n"
    "        sp = Path(matches[0]) if matches else None"
)


class ComfyEnvContractError(RuntimeError):
    """Isolation protocol is not the pinned 0.3.89 layout / source."""


def volume_root(workspace: str | Path) -> Path:
    return Path(workspace) / ".python" / "comfy-env"


def node_reqs_site(workspace: str | Path) -> Path:
    return Path(workspace) / ".python" / "node-reqs"


def installed_version(site: str | Path) -> str | None:
    """Read ``comfy-env`` dist-info Version from a site-packages directory."""
    versions: list[str] = []
    for meta in Path(site).glob("comfy_env-*.dist-info/METADATA"):
        try:
            for line in meta.read_text(encoding="utf-8").splitlines():
                if line.startswith("Version:"):
                    versions.append(line.split(":", 1)[1].strip())
                    break
        except OSError:
            continue
    if not versions:
        return None
    return sorted(versions, reverse=True)[0]


def isolation_worker(site: str | Path) -> Path:
    return Path(site) / "comfy_env" / "isolation" / "workers" / "subprocess.py"


def pin_satisfied(site: str | Path) -> bool:
    return isolation_worker(site).is_file() and installed_version(site) == VERSION


def remove_site_install(site: str | Path) -> None:
    root = Path(site)
    package = root / "comfy_env"
    if package.is_dir():
        shutil.rmtree(package)
    for meta in root.glob("comfy_env-*.dist-info"):
        shutil.rmtree(meta)


def assert_pinned(site: str | Path) -> None:
    version = installed_version(site)
    worker = isolation_worker(site)
    if version != VERSION or not worker.is_file():
        raise ComfyEnvContractError(
            f"{site} has comfy-env {version or 'missing'}, need {PIN} "
            f"with isolation worker {worker}. Do not install unpinned."
        )


def v03_python_bins(root: str | Path) -> list[Path]:
    return sorted(path for path in Path(root).glob(V03_PYTHON_GLOB) if path.is_file())


def v04_python_bins(root: str | Path) -> list[Path]:
    return sorted(path for path in Path(root).glob(V04_PYTHON_GLOB) if path.is_file())


def isolation_visible(root: str | Path) -> bool:
    """True when 0.3.89 wrap can see a pixi env (native 0.3 or bridged)."""
    return bool(v03_python_bins(root))


def env_materialized(root: str | Path) -> bool:
    """True when a pixi python exists in either layout (skip install.py)."""
    return bool(v03_python_bins(root) or v04_python_bins(root))


def isolation_python_bins(root: str | Path) -> list[Path]:
    """Prefer the 0.3 discovery path; fall back to a 0.4-only tree."""
    return v03_python_bins(root) or v04_python_bins(root)


def _v04_env_name(python: Path) -> str:
    # envs/<name>/.pixi/envs/default/bin/python
    return python.parents[4].name


def ensure_v03_layout(root: str | Path) -> bool:
    """Symlink a 0.4-only workspace so 0.3.89 wrap can find it.

    Returns True when a new link was created.
    """
    root = Path(root)
    if isolation_visible(root):
        return False
    changed = False
    for python in v04_python_bins(root):
        name = _v04_env_name(python)
        dest = root / ".pixi" / "envs" / name
        target = python.parent.parent  # .../default
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() or dest.is_symlink():
            continue
        dest.symlink_to(os.path.relpath(target, dest.parent), target_is_directory=True)
        changed = True
        print(f"[comfy-env] bridged 0.4 env {name} -> {dest} for 0.3 wrap", flush=True)
    return changed


def assert_isolation_visible(root: str | Path) -> None:
    if isolation_visible(root):
        return
    extra = ""
    if v04_python_bins(root):
        extra = (
            f" Found 0.4 layout {V04_PYTHON_GLOB} which {PIN} cannot see; "
            "bridge failed."
        )
    raise ComfyEnvContractError(
        f"{root} has no {V03_PYTHON_GLOB} for {PIN}.{extra} "
        "Refusing in-process import (host has no pytorch3d)."
    )


def _has_ready_anchor(text: str) -> bool:
    return READY_RECV_STOCK in text or READY_RECV_OURS in text


def _has_stdout_anchor(text: str) -> bool:
    return STDOUT_STOCK in text or STDOUT_OURS in text or WORKER_LOG in text


def _has_pixi_run_anchor(text: str) -> bool:
    return PIXI_RUN_STOCK in text or PIXI_RUN_OURS in text


def _has_is_pixi_anchor(text: str) -> bool:
    return bool(IS_PIXI_STOCK_RE.search(text)) or IS_PIXI_OURS in text


def _has_socket_timeout_anchor(text: str) -> bool:
    return bool(SOCKET_TIMEOUT_RE.search(text))


def _has_wrap_sp_anchor(text: str) -> bool:
    return WRAP_SP_STOCK in text or WRAP_SP_OURS in text or "matches.sort" in text


def assert_patchable(site: str | Path) -> None:
    """Fail if this install is the pin but the 0.3.89 source strings are gone.

    Silent no-op patches are how a float to 0.4 looked like 'already fine'.
    """
    site = Path(site)
    package = site if site.name == "comfy_env" else site / "comfy_env"
    if not package.is_dir():
        raise ComfyEnvContractError(f"comfy-env package missing under {site}")
    worker = package / "isolation" / "workers" / "subprocess.py"
    if not worker.is_file():
        raise ComfyEnvContractError(f"isolation worker missing: {worker}")
    text = worker.read_text(encoding="utf-8")
    missing: list[str] = []
    if not _has_ready_anchor(text):
        missing.append("ready recv timeout=60")
    if not _has_stdout_anchor(text):
        missing.append("stdout=DEVNULL")
    if PIXI_RUN_STOCK in text or PIXI_RUN_OURS in text or IS_PIXI_STOCK_RE.search(text):
        if not _has_pixi_run_anchor(text):
            missing.append("PIXI run --as-is")
        if not _has_is_pixi_anchor(text):
            missing.append("is_pixi")
    if missing:
        raise ComfyEnvContractError(
            f"{worker} is not {PIN} isolation source (missing {missing}). "
            f"Update {__name__} only after a new L40S smoke."
        )
    ipc = package / "isolation" / "workers" / "_ipc_shared.py"
    if ipc.is_file():
        ipc_text = ipc.read_text(encoding="utf-8")
        if not _has_socket_timeout_anchor(ipc_text):
            raise ComfyEnvContractError(
                f"{ipc} has no SOCKET_ACCEPT_TIMEOUT assignment; not {PIN}."
            )
    wrap = package / "isolation" / "wrap.py"
    if wrap.is_file():
        wrap_text = wrap.read_text(encoding="utf-8")
        if "lib/python*/site-packages" in wrap_text and not _has_wrap_sp_anchor(wrap_text):
            raise ComfyEnvContractError(
                f"{wrap} site-packages glob is not the {PIN} form."
            )


def assert_boot(workspace: str | Path, *, require_env: bool = True) -> None:
    """Boot-time checks: pin on the Volume site, 0.3 layout visible."""
    site = node_reqs_site(workspace)
    assert_pinned(site)
    assert_patchable(site)
    if require_env:
        assert_isolation_visible(volume_root(workspace))
