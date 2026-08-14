"""SAM 3D Objects pixi / comfy-env runtime on the workspace Volume.

PozzettiAndrea/ComfyUI-SAM3DObjects runs inference in an isolated pixi env.
The default Unix cache is ``~/.ce`` (ephemeral on Modal). Point
``COMFY_ENV_ROOT`` at ``/workspace/.python/comfy-env`` and run ``install.py``
only when the *current lock* asks for this node.

``comfy-env`` 0.3.x isolation workers ``Popen`` ``~/.pixi/bin/pixi`` as a
constant — they do not call ``ensure_pixi()``. That CLI is ephemeral on
Modal unless it is copied onto the workspace Volume and re-linked each boot.

``comfy-env-root.toml`` also lists GeometryPack / Multiband. The official
object-generation graph does not use those nodes, so they are stripped
before ``install.py`` — otherwise pixi would clone and build CGAL.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import urllib.request
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

COMFY_ENV_SITE_MARK = "comfy-env"
COMFY_ENV_ROOT_VAR = "COMFY_ENV_ROOT"
PIXI_VERSION = "0.76.2"
PIXI_LINUX_X64_URL = (
    "https://github.com/prefix-dev/pixi/releases/download/"
    f"v{PIXI_VERSION}/pixi-x86_64-unknown-linux-musl"
)
# comfy-env 0.3.x waits 60s for the isolation worker. First ``pixi run`` of a
# CUDA env is slower than that unless the lock is frozen and the timeout is raised.
WORKER_SOCKET_TIMEOUT_SECONDS = 600
_TIMEOUT_ASSIGN_RE = re.compile(r"^(SOCKET_ACCEPT_TIMEOUT\s*=\s*)\d+", re.M)
_PIXI_RUN_AS_IS = 'PIXI, "run", "--as-is",'
_PIXI_RUN_FROZEN = 'PIXI, "run", "--as-is", "--frozen",'
_IS_PIXI_RE = re.compile(r"is_pixi = ['\"]\.pixi['\"] in str\(self\.python\)")
_WRAP_SP_GLOB = (
    '        matches = glob.glob(str(env_dir / "lib/python*/site-packages"))\n'
    "        sp = Path(matches[0]) if matches else None"
)
_WRAP_SP_FIXED = (
    '        matches = glob.glob(str(env_dir / "lib/python*/site-packages"))\n'
    "        matches.sort(key=lambda p: tuple("
    "int(x) if str(x).isdigit() else 0 "
    "for x in Path(p).parent.name.replace('python', '', 1).split('.')), reverse=True)\n"
    "        sp = Path(matches[0]) if matches else None"
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
    return Path(workspace) / ".python" / "comfy-env"


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
    for pattern in (
        "envs/*/.pixi/envs/default/bin/python",
        ".pixi/envs/*/bin/python",
    ):
        if any(path.is_file() for path in root.glob(pattern)):
            return True
    return False


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


def _comfy_env_packages(comfy_root: Path) -> list[Path]:
    return sorted((Path(comfy_root) / "venv" / "lib").glob("python3.*/site-packages/comfy_env"))


def patch_comfy_env_isolation(comfy_root: str | Path) -> bool:
    """Make Image-local comfy-env 0.3.x isolation usable on a cold GPU boot.

    The Image venv is ephemeral; this rewrite is lock-gated and per container.
    """
    changed = False
    for site in _comfy_env_packages(Path(comfy_root)):
        ipc = site / "isolation" / "workers" / "_ipc_shared.py"
        if ipc.is_file():
            text = ipc.read_text(encoding="utf-8")
            updated, count = _TIMEOUT_ASSIGN_RE.subn(
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
            updated = text
            if _PIXI_RUN_AS_IS in updated and _PIXI_RUN_FROZEN not in updated:
                updated = updated.replace(_PIXI_RUN_AS_IS, _PIXI_RUN_FROZEN, 1)
            patched_pixi, n_pixi = _IS_PIXI_RE.subn("is_pixi = False", updated, count=1)
            if n_pixi:
                updated = patched_pixi
                print("[SAM3D] isolation worker uses env python (skip pixi run)", flush=True)
            if updated != text:
                worker.write_text(updated, encoding="utf-8")
                changed = True
        wrap = site / "isolation" / "wrap.py"
        if wrap.is_file():
            text = wrap.read_text(encoding="utf-8")
            if _WRAP_SP_GLOB in text:
                wrap.write_text(text.replace(_WRAP_SP_GLOB, _WRAP_SP_FIXED, 1), encoding="utf-8")
                changed = True
                print(
                    "[SAM3D] prefer python3.12 site-packages over python3.1 glob",
                    flush=True,
                )
    return changed


def _isolated_python_bins(root: Path) -> list[Path]:
    return sorted(root.glob(".pixi/envs/*/bin/python")) + sorted(
        root.glob("envs/*/.pixi/envs/default/bin/python")
    )


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
        _ce()._run([str(python), "-c", "print('sam3d-python-ok')"], env=env)


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
    pixi_changed = ensure_pixi_cli(workspace)
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
            print(
                f"[SAM3D] warning: install.py finished but no pixi python under {root}",
                flush=True,
            )
        installed = True
    patch_comfy_env_isolation(comfy_root)
    warm_pixi_env(workspace)
    return pixi_changed or installed
