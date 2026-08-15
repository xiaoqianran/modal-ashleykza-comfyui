"""GPU launch facade.

Download / CNR / process helpers live in ``asset_sync``, ``node_install``,
and ``engine_util``. This module re-exports them so tests and runtime hooks
can keep patching ``comfy_engine.ensure_*`` / ``_run``.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path

from asset_sync import (  # noqa: F401
    LAUNCH_STATE_FILE,
    LAUNCH_STATE_SCHEMA,
    LOCK_SCHEMA,
    WORKFLOW_LOCK_STATE_FILE,
    _asset_lock_entry,
    _download_with_aria2,
    _download_with_hf_cli,
    _extract_archive,
    _hf_auth_header,
    _hydrate_assets_parallel,
    _hydrate_one_asset,
    _is_asset_current,
    _load_lock,
    _lock_path,
    _parse_hf_url,
    _promote_legacy_if_needed,
    _safe_member_path,
    _save_lock,
    _sha256,
    _with_civitai_token,
    _write_json,
    asset_filename,
    download_asset,
    launch_fingerprint,
    load_launch_state,
    normalize_huggingface_url,
    output_manifest,
    persist_launch_state,
    redact_url,
    sync_profile_models,
    sync_workflow_models,
    verify_workflow_models,
)
from engine_util import (  # noqa: F401
    _comfy_python,
    _module_available,
    _module_import_error,
    _python_text,
    _quote,
    _run,
    _site_packages,
)
from node_install import (  # noqa: F401
    NODE_REQS_PTH_NAME,
    NODE_REQS_SITE_MARK,
    NODE_REQS_SKIP_PACKAGES,
    _cnr_marker_path,
    _dir_names,
    _github_repo_dir_name,
    _hash_requirements,
    _install_github_node,
    _install_node_requirements,
    _link_node_reqs_site,
    _node_req_marker,
    _registry_install_one,
    _remember_node_reqs,
    build_node_commands,
    build_registry_node_commands,
    ensure_node_reqs_site,
    install_registry_nodes,
    node_reqs_volume_path,
)
from recipes import MODEL_PACKS, get_profile, profile_comfy_args  # noqa: F401
from runtime_hooks import append_site_marks, matched_hooks, run_prepare, run_runtimes, run_wheels
from sam3d_runtime import (  # noqa: F401
    apply_comfy_env_root,
    ensure_sam3d_runtime,
)
from sparse_3d_runtime import (  # noqa: F401
    NATTEN_WHEEL_INDEX,
    SPARSE_3D_PTH_NAME,
    SPARSE_3D_SITE_MARK,
    _alias_sparse_3d_packages,
    _download_file,
    _ensure_cached_wheel,
    _ensure_cuda_build_tools,
    _ensure_opengl_libs,
    _find_pixal3d_node_dir,
    _install_blackwell_boot,
    _install_flash_attn_wheel,
    _install_natten_wheel,
    _install_sparse_3d_prebuilt_wheels,
    _install_sparse_3d_python_deps,
    _install_trellis2_python_deps,
    _link_sparse_3d_site,
    _lock_has_pixal3d,
    _lock_has_trellis2,
    _lock_needs_sparse_3d_runtime,
    _pip_install,
    _prepare_sparse_3d_site,
    ensure_pixal3d_prebuilt_wheels,
    ensure_pixal3d_runtime,
    ensure_sparse_3d_prebuilt_wheels,
    ensure_sparse_3d_runtime,
    flash_attn_wheel_url,
    natten_requirement_version,
    natten_wheel_spec,
    requirements_without_packages,
    sparse_3d_volume_paths,
    sparse_3d_wheel_urls,
)
from storage import (
    DEFAULT_STORAGE_ROOT,
    ensure_storage_layout,
    ensure_workspace_layout,
    extra_model_paths_yaml,
    repair_storage_layout,
    repair_workspace_layout,
)


def stop_comfyui(process: subprocess.Popen | None, *, timeout: float = 15.0) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=timeout)
    except Exception:  # noqa: BLE001
        try:
            process.kill()
        except OSError:
            return


def write_extra_model_paths(
    comfy_root: str | Path,
    workspace: str | Path,
    storage_root: str | Path = DEFAULT_STORAGE_ROOT,
) -> Path:
    """Write ComfyUI extra_model_paths.yaml with Volume dirs mapped 1:1."""
    path = Path(comfy_root) / "extra_model_paths.yaml"
    path.write_text(
        extra_model_paths_yaml(storage_root=storage_root, workspace=workspace),
        encoding="utf-8",
    )
    return path


def _replace_with_symlink(link_path: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink():
        if link_path.resolve() == target.resolve():
            return
        link_path.unlink()
    elif link_path.exists():
        backup = link_path.with_name(link_path.name + ".image-bak")
        if backup.exists():
            if link_path.is_dir():
                shutil.rmtree(link_path)
            else:
                link_path.unlink()
        else:
            link_path.rename(backup)
    link_path.symlink_to(target, target_is_directory=True)


def prepare_runtime(
    comfy_root: str | Path = "/ComfyUI",
    workspace: str | Path = "/workspace",
    storage_root: str | Path = DEFAULT_STORAGE_ROOT,
) -> None:
    comfy_root = Path(comfy_root)
    workspace = Path(workspace)
    storage_root = Path(storage_root)

    if not (comfy_root / "main.py").exists():
        raise RuntimeError(f"ComfyUI main.py not found under {comfy_root}")

    ensure_workspace_layout(workspace)
    ensure_storage_layout(storage_root)
    repair_workspace_layout(workspace)
    repair_storage_layout(storage_root)
    write_extra_model_paths(comfy_root, workspace, storage_root)

    for name in ("input", "output", "user"):
        _replace_with_symlink(comfy_root / name, workspace / name)
    # Some loaders join folder_paths.models_dir / "<category>/..." instead of
    # extra_model_paths. Point those Image dirs at the Volume.
    models_dir = comfy_root / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    for name in ("microsoft", "facebook", "sam3dobjects"):
        _replace_with_symlink(models_dir / name, storage_root / name)

    write_optional_node_configs(comfy_root, workspace)


def apply_volume_launch(
    *,
    storage_root: str | Path,
    workspace: str | Path,
    comfy_root: str | Path,
    default_profile: str,
    default_install_lock_nodes: bool,
    previous_fingerprint: str | None = None,
    process: subprocess.Popen | None = None,
    extra_args: tuple[str, ...] | list[str] = (),
    port: int = 3001,
    startup_timeout: int = 900,
    install_nodes: Callable[..., list[str]] | None = None,
    start_fn: Callable[..., subprocess.Popen] | None = None,
    wait_fn: Callable[..., None] | None = None,
) -> tuple[subprocess.Popen, str, list[str]]:
    """Repair Volume layout, verify models, install lock CNR, start/restart ComfyUI.

    Call this after ``Volume.reload()`` on every container start (``snap=False``)
    so hydrate can change ``launch.json`` without freezing it into a memory
    snapshot. Restarts ComfyUI when the launch fingerprint changes or CNR was
    newly installed.
    """
    comfy_root = Path(comfy_root)
    workspace = Path(workspace)
    storage_root = Path(storage_root)
    prepare_runtime(comfy_root, workspace, storage_root)
    launch = load_launch_state(storage_root) or {}
    workflow_lock = launch.get("workflow_lock")
    profile_name = str(launch.get("profile") or default_profile or "base")
    install_lock_nodes = bool(launch.get("install_lock_nodes", default_install_lock_nodes))
    if isinstance(workflow_lock, Mapping) and workflow_lock:
        verify_workflow_models(
            workflow_lock,
            workspace,
            storage_root=storage_root,
        )
    newly: list[str] = []
    nodes = list((workflow_lock or {}).get("custom_nodes") or ()) if isinstance(workflow_lock, Mapping) else []
    installer = install_nodes or install_registry_nodes
    hooks = matched_hooks(nodes)
    # Look up ensure_* on this module so tests can patch comfy_engine.ensure_*.
    engine = sys.modules[__name__]
    # Env-root prepare is cheap and must run even when CNR install is skipped.
    run_prepare(engine, hooks, workspace)
    wheels_changed = False
    runtime_changed = False
    if install_lock_nodes:
        # Wheels first so CNR / TRELLIS.2 do not compile CUDA sdists.
        wheels_changed = run_wheels(
            engine,
            hooks,
            comfy_root=comfy_root,
            workspace=workspace,
            nodes=nodes,
        )
        if nodes:
            ensure_node_reqs_site(comfy_root, workspace)
            newly = installer(
                nodes,
                comfy_root=comfy_root,
                custom_nodes_dir=workspace / "custom_nodes",
            )
        runtime_changed = run_runtimes(
            engine,
            hooks,
            comfy_root=comfy_root,
            workspace=workspace,
            nodes=nodes,
        )
    fingerprint = launch_fingerprint(
        launch,
        profile_name=profile_name,
        install_lock_nodes=install_lock_nodes,
    )
    start = start_fn or start_comfyui
    wait = wait_fn or wait_comfyui_ready
    need_restart = (
        process is None
        or process.poll() is not None
        or previous_fingerprint != fingerprint
        or bool(newly)
        or wheels_changed
        or runtime_changed
    )
    if need_restart:
        stop_comfyui(process)
        process = start(
            profile_name=profile_name,
            comfy_root=comfy_root,
            workspace=workspace,
            port=port,
            extra_args=extra_args,
        )
        wait(port=port, timeout=startup_timeout)
    assert process is not None
    newly = append_site_marks(
        newly,
        hooks,
        changed=wheels_changed or runtime_changed,
    )
    return process, fingerprint, newly


def write_optional_node_configs(comfy_root: Path, workspace: Path) -> None:
    """Materialize secret-backed node config without storing credentials in Git.

    Only write next to the Image-local node copy. The workspace Volume is
    persistent; putting API keys there would outlive the Modal Secret.
    """
    del workspace  # Volume-backed custom_nodes must not receive secret files.
    node = comfy_root / "custom_nodes" / "ComfyUI-OllamaGemini"
    if not node.exists():
        return

    values = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
        "OLLAMA_URL": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        "QWEN_API_KEY": os.environ.get("QWEN_API_KEY", ""),
    }
    if not any(values[key] for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "QWEN_API_KEY")):
        return

    config_path = node / "config.json"
    config_path.write_text(
        json.dumps(values, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    print("Wrote secret-backed ComfyUI-OllamaGemini/config.json")


def start_comfyui(
    *,
    profile_name: str,
    comfy_root: str | Path = "/ComfyUI",
    workspace: str | Path = "/workspace",
    port: int = 3001,
    extra_args: tuple[str, ...] | list[str] = (),
) -> subprocess.Popen:
    comfy_root = Path(comfy_root)
    workspace = Path(workspace)
    python = comfy_root / "venv" / "bin" / "python3"
    if not python.exists():
        python = comfy_root / "venv" / "bin" / "python"
    if not python.exists():
        python = Path("python3")

    cmd = [
        str(python),
        str(comfy_root / "main.py"),
        "--listen", "0.0.0.0",
        "--port", str(port),
        "--input-directory", str(workspace / "input"),
        "--output-directory", str(workspace / "output"),
        "--user-directory", str(workspace / "user"),
        *profile_comfy_args(profile_name),
        *extra_args,
    ]

    log_path = workspace / "logs" / "comfyui.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", buffering=1)
    print("Starting:", " ".join(shlex.quote(arg) for arg in cmd))
    process = subprocess.Popen(
        cmd,
        cwd=str(comfy_root),
        stdout=log,
        stderr=log,
    )
    log.close()
    time.sleep(2)
    if process.poll() is not None:
        tail = ""
        try:
            tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:])
        except OSError:
            pass
        raise RuntimeError(f"ComfyUI exited during startup (code={process.returncode}).\n{tail}")
    return process


def wait_comfyui_ready(*, port: int, timeout: int = 600) -> None:
    """Block until the local ComfyUI HTTP server answers /system_stats."""
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/system_stats"
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=5)
            print(f"ComfyUI ready on :{port}", flush=True)
            return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(1)
    raise RuntimeError(f"ComfyUI did not become ready on :{port} within {timeout}s")
