"""CPU ComfyUI probe: start without a GPU, then list missing nodes / files.

This is step A/B of hydrate --action probe. CUDA-only custom nodes may fail
to import on CPU; Manager catalogs still identify those packs. Models are
checked against the Volume on disk.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from recipes import MODEL_DIRS
from storage import extra_model_paths_yaml, storage_model_path
from workflow_resolver import _nodes

# Keep this skip set aligned with workflow_queue.SKIP_OBJECT_INFO_TYPES.
SKIP_OBJECT_INFO_TYPES = frozenset(
    {
        "Note",
        "MarkdownNote",
        "Reroute",
        "GetNode",
        "SetNode",
        "Graph",
    }
)
SUBGRAPH_TYPE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

CPU_COMFY_DIR = Path(".cpu-comfy")
COMFY_REPO = "https://github.com/comfyanonymous/ComfyUI.git"
MANAGER_REPO = "https://github.com/Comfy-Org/ComfyUI-Manager.git"


def workflow_class_types(workflow: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for node in _nodes(workflow):
        name = str(node.get("type") or node.get("class_type") or "").strip()
        if (
            not name
            or name in seen
            or name in SKIP_OBJECT_INFO_TYPES
            or name.startswith("Primitive")
            or SUBGRAPH_TYPE_RE.fullmatch(name)
        ):
            continue
        seen.add(name)
        names.append(name)
    return names


def missing_node_types(
    required: Iterable[str],
    object_info: Mapping[str, Any] | None,
) -> list[str]:
    present = object_info if isinstance(object_info, Mapping) else {}
    return [name for name in required if name not in present]


def missing_model_files(
    models: Iterable[Mapping[str, Any]],
    storage_root: str | Path,
) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    root = Path(storage_root)
    for model in models:
        category = str(model.get("category") or "")
        filename = str(model.get("filename") or "")
        if category not in MODEL_DIRS or not filename:
            continue
        path = storage_model_path(root, category, filename)
        if not path.is_file():
            missing.append(
                {
                    "category": category,
                    "filename": filename,
                    "path": str(path),
                }
            )
    return missing


def write_cpu_extra_paths(*, comfy_root: Path, storage_root: Path, workspace: Path) -> Path:
    path = comfy_root / "extra_model_paths.yaml"
    path.write_text(
        extra_model_paths_yaml(storage_root=storage_root, workspace=workspace),
        encoding="utf-8",
    )
    return path


def cpu_comfy_root(workspace: str | Path) -> Path:
    return Path(workspace) / CPU_COMFY_DIR / "ComfyUI"


def cpu_venv_python(workspace: str | Path) -> Path:
    return Path(workspace) / CPU_COMFY_DIR / "venv" / "bin" / "python"


def _run(args: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def ensure_cpu_runtime(
    workspace: str | Path,
    *,
    clone: bool = True,
    install: bool = True,
) -> dict[str, str]:
    """Clone ComfyUI + Manager onto the workspace Volume (CPU torch)."""
    workspace = Path(workspace)
    root = cpu_comfy_root(workspace)
    venv_python = cpu_venv_python(workspace)
    manager = root / "custom_nodes" / "ComfyUI-Manager"
    if clone and not (root / "main.py").is_file():
        root.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--depth", "1", COMFY_REPO, str(root)])
    if clone and not (manager / "cm-cli.py").is_file():
        manager.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--depth", "1", MANAGER_REPO, str(manager)])
    if install and not venv_python.is_file():
        _run(["python3", "-m", "venv", str(venv_python.parent.parent)])
        _run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "-U",
                "pip",
                "torch",
                "torchvision",
                "torchaudio",
                "--index-url",
                "https://download.pytorch.org/whl/cpu",
            ]
        )
        requirements = root / "requirements.txt"
        if requirements.is_file():
            _run([str(venv_python), "-m", "pip", "install", "-r", str(requirements)])
        manager_requirements = manager / "requirements.txt"
        if manager_requirements.is_file():
            _run([str(venv_python), "-m", "pip", "install", "-r", str(manager_requirements)])
        # ComfyUI requirements.txt may pull a CUDA wheel. Force CPU torch back.
        _run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "torch",
                "torchvision",
                "torchaudio",
                "--index-url",
                "https://download.pytorch.org/whl/cpu",
            ]
        )
    return {
        "comfy_root": str(root),
        "python": str(venv_python),
        "manager": str(manager),
    }


def start_cpu_comfy(
    *,
    python: str | Path,
    comfy_root: str | Path,
    port: int = 8188,
    extra_paths: str | Path | None = None,
) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["COMFYUI_PATH"] = str(comfy_root)
    args = [
        str(python),
        str(Path(comfy_root) / "main.py"),
        "--cpu",
        "--listen",
        "127.0.0.1",
        "--port",
        str(port),
        "--disable-auto-launch",
    ]
    if extra_paths:
        args.extend(["--extra-model-paths-config", str(extra_paths)])
    return subprocess.Popen(
        args,
        cwd=str(comfy_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def stop_cpu_comfy(proc: subprocess.Popen[str], timeout: int = 20) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()


def http_json(url: str, timeout: int = 20) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_cpu_ready(base: str, timeout: int = 300) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            stats = http_json(f"{base.rstrip('/')}/system_stats", timeout=10)
            if isinstance(stats, dict):
                return stats
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last = exc
        time.sleep(2)
    raise TimeoutError(f"CPU ComfyUI not ready: {last}")


def probe_running(
    base: str,
    workflow: Mapping[str, Any],
    *,
    models: Iterable[Mapping[str, Any]],
    storage_root: str | Path,
) -> dict[str, Any]:
    info: Mapping[str, Any] | None
    try:
        fetched = http_json(f"{base.rstrip('/')}/object_info", timeout=30)
        info = fetched if isinstance(fetched, dict) else {}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        info = {}
    required = workflow_class_types(workflow)
    missing_nodes = missing_node_types(required, info)
    return {
        "missing_nodes": missing_nodes,
        "missing_models": missing_model_files(models, storage_root),
        "required_nodes": required,
        "object_info_count": len(info or {}),
    }
