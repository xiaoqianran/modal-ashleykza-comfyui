"""SAM 3D Objects pixi runtime on the workspace Volume.

PozzettiAndrea/ComfyUI-SAM3DObjects runs inference in an isolated pixi env.
The isolation *protocol* (pin, layout, fail-loud checks) lives in
``comfy_env_contract``. This module only: persist pixi on the Volume, run
``install.py`` when the lock asks for the node, and apply the known 0.3.89
Modal patches.

``comfy-env-root.toml`` also lists GeometryPack / Multiband. The official
object-generation graph does not use those nodes, so they are stripped
before ``install.py`` — otherwise pixi would clone and build CGAL.
"""

from __future__ import annotations

import os
import shutil
import stat
import urllib.request
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import comfy_env_contract as _ce_contract
from comfy_env_contract import (
    IS_PIXI_OURS,
    IS_PIXI_STOCK_RE,
    PIXI_RUN_OURS,
    PIXI_RUN_STOCK,
    READY_RECV_OURS,
    READY_RECV_STOCK,
    SOCKET_TIMEOUT_RE,
    STDOUT_OURS,
    STDOUT_STOCK,
    WORKER_LOG,
    WRAP_SP_OURS,
    WRAP_SP_STOCK,
    assert_boot,
    assert_patchable,
    assert_pinned,
    ensure_v03_layout,
    env_materialized,
    isolation_python_bins,
    node_reqs_site,
    pin_satisfied,
    remove_site_install,
    volume_root,
)
from comfy_env_contract import (
    PIN as COMFY_ENV_PIN,
)
from comfy_env_contract import (
    READY_TIMEOUT_SECONDS as WORKER_SOCKET_TIMEOUT_SECONDS,
)
from comfy_env_contract import (
    ROOT_VAR as COMFY_ENV_ROOT_VAR,
)

COMFY_ENV_SITE_MARK = _ce_contract.SITE_MARK
COMFY_ENV_VERSION = _ce_contract.VERSION

PIXI_VERSION = "0.76.2"
PIXI_LINUX_X64_URL = (
    "https://github.com/prefix-dev/pixi/releases/download/"
    f"v{PIXI_VERSION}/pixi-x86_64-unknown-linux-musl"
)
_STRIPPED_NODE_REQS = """\
# GeometryPack / Multiband are not in the object-generation graph.
# install.py would clone them and pixi-build CGAL.
[node_reqs]
"""


def _ce():
    import comfy_engine

    return comfy_engine


def comfy_env_root(workspace: str | Path) -> Path:
    return volume_root(workspace)


def volume_pixi_bin(workspace: str | Path) -> Path:
    return Path(workspace) / ".python" / "pixi" / "bin" / "pixi"


def home_pixi_bin() -> Path:
    """Path comfy-env 0.3.x isolation workers exec (``PIXI`` constant)."""
    return Path.home() / ".pixi" / "bin" / "pixi"


def apply_comfy_env_root(workspace: str | Path) -> Path:
    """Persist pixi envs on the workspace Volume and export COMFY_ENV_ROOT."""
    root = comfy_env_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    os.environ[COMFY_ENV_ROOT_VAR] = str(root)
    return root


def _lock_has_sam3d(nodes: Iterable[Mapping[str, Any]]) -> bool:
    for node in nodes:
        node_id = str(node.get("id") or "").lower()
        if "sam3dobjects" in node_id or "sam-3d-objects" in node_id:
            return True
    return False


def _find_sam3d_node_dir(custom_nodes_dir: Path) -> Path | None:
    if not custom_nodes_dir.is_dir():
        return None
    for item in sorted(custom_nodes_dir.iterdir()):
        if item.is_dir() and "sam3dobjects" in item.name.lower():
            return item
    return None


def _pixi_env_ready(root: Path) -> bool:
    return env_materialized(root)


def _chmod_exec(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _download_pixi(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    print(f"[SAM3D] downloading pixi {PIXI_VERSION} -> {dest}", flush=True)
    with urllib.request.urlopen(PIXI_LINUX_X64_URL, timeout=120) as response:
        tmp.write_bytes(response.read())
    if tmp.read_bytes()[:4] != b"\x7fELF":
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"pixi download was not an ELF binary: {PIXI_LINUX_X64_URL}")
    _chmod_exec(tmp)
    os.replace(tmp, dest)


def _link_home_pixi(volume_bin: Path) -> None:
    home_bin = home_pixi_bin()
    home_bin.parent.mkdir(parents=True, exist_ok=True)
    if home_bin.is_symlink() or home_bin.exists():
        if home_bin.is_symlink() and home_bin.resolve() == volume_bin.resolve():
            return
        home_bin.unlink()
    home_bin.symlink_to(volume_bin)


def _prepend_path(directory: Path) -> None:
    value = str(directory)
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if value not in parts:
        os.environ["PATH"] = os.pathsep.join([value, *parts]) if parts else value


def ensure_pixi_cli(workspace: str | Path) -> bool:
    """Keep ``pixi`` on the Volume and expose it at ``~/.pixi/bin/pixi``.

    Returns True when the Volume copy was created this call (needs commit).
    """
    volume_bin = volume_pixi_bin(workspace)
    home_bin = home_pixi_bin()
    changed = False
    if (
        home_bin.is_file()
        and not home_bin.is_symlink()
        and home_bin.resolve() != volume_bin.resolve()
        and not volume_bin.is_file()
    ):
        volume_bin.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(home_bin, volume_bin)
        _chmod_exec(volume_bin)
        changed = True
        print(f"[SAM3D] copied pixi onto Volume {volume_bin}", flush=True)
    if not volume_bin.is_file():
        _download_pixi(volume_bin)
        changed = True
    _link_home_pixi(volume_bin)
    _prepend_path(volume_bin.parent)
    return changed


def _comfy_env_packages(
    comfy_root: Path,
    workspace: str | Path | None = None,
) -> list[Path]:
    found = list((Path(comfy_root) / "venv" / "lib").glob("python3.*/site-packages/comfy_env"))
    if workspace is not None:
        extra = Path(workspace) / ".python" / "node-reqs" / "comfy_env"
        if extra.is_dir():
            found.append(extra)
    return sorted(found, key=lambda path: str(path))


def _installed_comfy_env_version(site: str | Path) -> str | None:
    return _ce_contract.installed_version(site)


def _ensure_volume_comfy_env(workspace: str | Path, python: str) -> bool:
    """Keep the pinned isolation library on the Volume site.

    The Image may not ship ``comfy-env``. The parent imports this copy via
    ``comfy_node_reqs.pth``. Pin, layout, and fail-loud checks are in
    ``comfy_env_contract`` — this only runs ``uv pip``.
    """
    from uv_runtime import pip_install_cmd

    site = node_reqs_site(workspace)
    if pin_satisfied(site):
        assert_patchable(site)
        return False
    version = _ce_contract.installed_version(site)
    site.mkdir(parents=True, exist_ok=True)
    if (site / "comfy_env").is_dir() or version:
        print(
            f"[SAM3D] replacing Volume comfy-env {version or 'unknown'} with {COMFY_ENV_PIN}",
            flush=True,
        )
        remove_site_install(site)
    else:
        print(f"[SAM3D] installing {COMFY_ENV_PIN} onto Volume site {site}", flush=True)
    _ce()._run(pip_install_cmd(python, COMFY_ENV_PIN, site_dir=site))
    assert_pinned(site)
    return True


def _require_anchor(path: Path, text: str, present: bool, name: str) -> None:
    if not present:
        raise _ce_contract.ComfyEnvContractError(
            f"{path} is not {COMFY_ENV_PIN} isolation source ({name} missing). "
            "Refusing to no-op. Update comfy_env_contract after a new L40S smoke."
        )


def patch_comfy_env_isolation(
    comfy_root: str | Path,
    workspace: str | Path | None = None,
) -> bool:
    """Make pinned 0.3.89 isolation usable on a cold GPU boot.

    Rewrites are lock-gated and per container. Missing 0.3.89 source strings
    raise — they must not silently skip.
    """
    changed = False
    sites = _comfy_env_packages(Path(comfy_root), workspace)
    if not sites:
        raise _ce_contract.ComfyEnvContractError(
            f"{COMFY_ENV_PIN} package missing under {comfy_root} / {workspace}"
        )
    for site in sites:
        print(f"[SAM3D] patching isolation at {site}", flush=True)
        ipc = site / "isolation" / "workers" / "_ipc_shared.py"
        if ipc.is_file():
            text = ipc.read_text(encoding="utf-8")
            _require_anchor(
                ipc,
                text,
                bool(SOCKET_TIMEOUT_RE.search(text)),
                "SOCKET_ACCEPT_TIMEOUT",
            )
            updated, count = SOCKET_TIMEOUT_RE.subn(
                rf"\g<1>{WORKER_SOCKET_TIMEOUT_SECONDS}",
                text,
                count=1,
            )
            if count and updated != text:
                ipc.write_text(updated, encoding="utf-8")
                changed = True
                print(
                    f"[SAM3D] SOCKET_ACCEPT_TIMEOUT -> {WORKER_SOCKET_TIMEOUT_SECONDS}s",
                    flush=True,
                )
        worker = site / "isolation" / "workers" / "subprocess.py"
        if worker.is_file():
            text = worker.read_text(encoding="utf-8")
            _require_anchor(
                worker,
                text,
                READY_RECV_STOCK in text or READY_RECV_OURS in text,
                "ready recv",
            )
            _require_anchor(
                worker,
                text,
                STDOUT_STOCK in text or STDOUT_OURS in text or WORKER_LOG in text,
                "stdout",
            )
            updated = text
            if PIXI_RUN_STOCK in updated and PIXI_RUN_OURS not in updated:
                updated = updated.replace(PIXI_RUN_STOCK, PIXI_RUN_OURS, 1)
            patched_pixi, n_pixi = IS_PIXI_STOCK_RE.subn(IS_PIXI_OURS, updated, count=1)
            if n_pixi:
                updated = patched_pixi
                print("[SAM3D] isolation worker uses env python (skip pixi run)", flush=True)
            if READY_RECV_STOCK in updated:
                updated = updated.replace(READY_RECV_STOCK, READY_RECV_OURS)
                print(
                    f"[SAM3D] ready recv timeout -> {WORKER_SOCKET_TIMEOUT_SECONDS}s",
                    flush=True,
                )
            if STDOUT_STOCK in updated:
                updated = updated.replace(STDOUT_STOCK, STDOUT_OURS, 1)
                print(f"[SAM3D] isolation worker stdout -> {WORKER_LOG}", flush=True)
            if updated != text:
                worker.write_text(updated, encoding="utf-8")
                changed = True
        wrap = site / "isolation" / "wrap.py"
        if wrap.is_file():
            text = wrap.read_text(encoding="utf-8")
            if "lib/python*/site-packages" in text:
                _require_anchor(
                    wrap,
                    text,
                    WRAP_SP_STOCK in text or WRAP_SP_OURS in text or "matches.sort" in text,
                    "site-packages glob",
                )
            if WRAP_SP_STOCK in text:
                wrap.write_text(text.replace(WRAP_SP_STOCK, WRAP_SP_OURS, 1), encoding="utf-8")
                changed = True
                print(
                    "[SAM3D] prefer python3.12 site-packages over python3.1 glob",
                    flush=True,
                )
        assert_patchable(site)
    return changed


def _isolated_python_bins(root: Path) -> list[Path]:
    return isolation_python_bins(root)


def apply_isolated_env(workspace: str | Path) -> Path | None:
    """Export conda-style activation so the worker can skip ``pixi run``."""
    pythons = _isolated_python_bins(comfy_env_root(workspace))
    if not pythons:
        return None
    prefix = pythons[0].parent.parent
    os.environ["CONDA_PREFIX"] = str(prefix)
    os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    _prepend_path(prefix / "bin")
    lib = prefix / "lib"
    if lib.is_dir():
        current = os.environ.get("LD_LIBRARY_PATH", "")
        value = str(lib)
        parts = current.split(os.pathsep) if current else []
        if value not in parts:
            os.environ["LD_LIBRARY_PATH"] = os.pathsep.join([value, *parts]) if parts else value
    print(f"[SAM3D] isolated env prefix {prefix}", flush=True)
    return prefix


def warm_pixi_env(workspace: str | Path) -> None:
    """Start the isolated interpreter once so a missing python fails at boot."""
    apply_isolated_env(workspace)
    pythons = _isolated_python_bins(comfy_env_root(workspace))
    env = os.environ.copy()
    for python in pythons:
        print(f"[SAM3D] warming isolated python {python}", flush=True)
        _ce()._run(
            [
                str(python),
                "-c",
                "import torch; print('sam3d-python-ok', torch.__version__, "
                "bool(torch.cuda.is_available()))",
            ],
            env=env,
        )


def _strip_optional_node_reqs(node_dir: Path) -> bool:
    path = node_dir / "comfy-env-root.toml"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if "ComfyUI-GeometryPack" not in text and "ComfyUI-Multiband" not in text:
        return False
    path.write_text(_STRIPPED_NODE_REQS, encoding="utf-8")
    print("[SAM3D] stripped GeometryPack / Multiband node_reqs", flush=True)
    return True


def ensure_sam3d_runtime(
    comfy_root: str | Path,
    custom_nodes_dir: str | Path,
    *,
    workspace: str | Path,
) -> bool:
    """Materialize the SAM 3D pixi env onto the workspace Volume.

    Returns True if ``install.py`` ran or pixi was newly stored (Volume commit).
    """
    custom_nodes_dir = Path(custom_nodes_dir)
    node_dir = _find_sam3d_node_dir(custom_nodes_dir)
    if node_dir is None:
        print("[SAM3D] ComfyUI-SAM3DObjects not on Volume; skip pixi", flush=True)
        return False
    root = apply_comfy_env_root(workspace)
    (Path(workspace) / "logs").mkdir(parents=True, exist_ok=True)
    pixi_changed = ensure_pixi_cli(workspace)
    python = _ce()._comfy_python(Path(comfy_root))
    volume_comfy_env = _ensure_volume_comfy_env(workspace, python)
    installed = False
    if _pixi_env_ready(root):
        print(f"[SAM3D] pixi env already on Volume {root}", flush=True)
    else:
        _strip_optional_node_reqs(node_dir)
        install = node_dir / "install.py"
        if not install.is_file():
            raise RuntimeError(f"SAM 3D install.py missing: {install}")
        python = _ce()._comfy_python(Path(comfy_root))
        env = os.environ.copy()
        env[COMFY_ENV_ROOT_VAR] = str(root)
        env["COMFY_ENV_INSTALL_ISOLATED"] = "1"
        print(f"[SAM3D] running {install} COMFY_ENV_ROOT={root}", flush=True)
        _ce()._run([python, str(install)], env=env, cwd=str(node_dir))
        ensure_pixi_cli(workspace)
        if not _pixi_env_ready(root):
            raise _ce_contract.ComfyEnvContractError(
                f"install.py finished but no pixi python under {root} "
                f"({_ce_contract.V03_PYTHON_GLOB} or {_ce_contract.V04_PYTHON_GLOB})"
            )
        installed = True
    bridged = ensure_v03_layout(root)
    patch_comfy_env_isolation(comfy_root, workspace=workspace)
    assert_boot(workspace, require_env=True)
    warm_pixi_env(workspace)
    return pixi_changed or installed or volume_comfy_env or bridged
