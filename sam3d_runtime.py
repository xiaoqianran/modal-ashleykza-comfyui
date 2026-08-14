"""SAM 3D Objects pixi / comfy-env runtime on the workspace Volume.

PozzettiAndrea/ComfyUI-SAM3DObjects runs inference in an isolated pixi env.
The default Unix cache is ``~/.ce`` (ephemeral on Modal). Point
``COMFY_ENV_ROOT`` at ``/workspace/.python/comfy-env`` and run ``install.py``
only when the *current lock* asks for this node.

``comfy-env-root.toml`` also lists GeometryPack / Multiband. The official
object-generation graph does not use those nodes, so they are stripped
before ``install.py`` — otherwise pixi would clone and build CGAL.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

COMFY_ENV_SITE_MARK = "comfy-env"
COMFY_ENV_ROOT_VAR = "COMFY_ENV_ROOT"
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

    Returns True if ``install.py`` ran (ComfyUI should restart; Volume commit).
    """
    custom_nodes_dir = Path(custom_nodes_dir)
    node_dir = _find_sam3d_node_dir(custom_nodes_dir)
    if node_dir is None:
        print("[SAM3D] ComfyUI-SAM3DObjects not on Volume; skip pixi", flush=True)
        return False
    root = apply_comfy_env_root(workspace)
    if _pixi_env_ready(root):
        print(f"[SAM3D] pixi env already on Volume {root}", flush=True)
        return False
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
    if not _pixi_env_ready(root):
        print(
            f"[SAM3D] warning: install.py finished but no pixi python under {root}",
            flush=True,
        )
    return True
