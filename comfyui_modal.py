"""Deploy ashleykleynhans/comfyui on Modal with declarative recipes.

Architecture:
- Image: Ashley runtime + optional GitHub base nodes + profile extras + CNR nodes.
- Models Volume: ComfyUI-shaped ``vae/``, ``text_encoders/``, ``diffusion_models/``, ...
- Workspace Volume: input / output / user / logs / optional user nodes.
- CPU hydrate: parallel downloads into Modal Storage, no GPU.
- GPU web server: mounts Storage, verifies files, never downloads.

``modal serve`` / ``modal deploy`` reuse the Image cache unless ``COMFY_LATEST=1``.

Examples:
    modal run comfyui_modal.py --action profiles
    modal run comfyui_modal.py --action hydrate --profile qwen-image
    modal run comfyui_modal.py --action hydrate --workflow workflow.json
    modal run comfyui_modal.py --action resolve --workflow workflow.json

    COMFY_PROFILE=qwen-image modal serve comfyui_modal.py
    COMFY_PROFILE=qwen-image modal deploy comfyui_modal.py
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

import modal

from base_nodes import INSTALLER_REMOTE_PATH, build_base_nodes_commands
from comfy_engine import (
    build_node_commands,
    build_registry_node_commands,
    prepare_runtime,
    start_comfyui,
    sync_profile_models,
    sync_workflow_models,
    verify_workflow_models,
)
from modal_config import ModalSettings, wants_gpu_runtime
from recipes import PROFILES, get_profile
from workflow_resolver import (
    load_workflow_lock,
    validate_workflow_lock,
    write_workflow_lock,
)

SETTINGS = ModalSettings.from_env(os.environ)
APP_NAME = SETTINGS.app_name
IMAGE_TAG = SETTINGS.image_tag
COMFY_ROOT = Path("/ComfyUI")
WORKSPACE = Path("/workspace")
STORAGE_ROOT = Path(SETTINGS.storage_root)
HYDRATE_WORKERS = SETTINGS.hydrate_workers
COMFY_PORT = 3001
MINUTES = 60
IMAGE_WORKFLOW_LOCK = Path("/opt/comfy/workflow.lock.json")

PROFILE_NAME = SETTINGS.profile_name
PROFILE = get_profile(PROFILE_NAME)
WORKFLOW_LOCK_SOURCE = SETTINGS.workflow_lock_source
BUILD_WORKFLOW_LOCK = (
    load_workflow_lock(WORKFLOW_LOCK_SOURCE, require_resolved=True)
    if WORKFLOW_LOCK_SOURCE and modal.is_local()
    else None
)
FORCE_LATEST = SETTINGS.latest_dependencies
BASE_NODES_ENABLED = SETTINGS.base_nodes_enabled

GPU = list(SETTINGS.gpu)

# Always use a named Modal Secret so local/remote dependency graphs match.
# Conditional from_dotenv(.env) breaks hydration: .env exists locally but not
# inside the remote container, so Modal sees a different object graph.
SECRET_NAME = SETTINGS.secret_name
APP_SECRETS = [modal.Secret.from_name(SECRET_NAME)]

app = modal.App(APP_NAME)
workspace_vol = modal.Volume.from_name(
    SETTINGS.volume_name,
    create_if_missing=True,
)
models_vol = modal.Volume.from_name(
    SETTINGS.models_volume_name,
    create_if_missing=True,
)
APP_VOLUMES = {
    str(WORKSPACE): workspace_vol,
    str(STORAGE_ROOT): models_vol,
}


BUILD_GPU_RUNTIME = wants_gpu_runtime()

# Stable profile nodes and workflow-declared CNR nodes are installed in CPU Image builds.
# Skip this entire Image when running CPU hydrate so we do not clone 130 GitHub repos.
node_commands = build_node_commands(PROFILE.node_packs) if BUILD_GPU_RUNTIME else []
registry_node_commands = (
    build_registry_node_commands(
        BUILD_WORKFLOW_LOCK["custom_nodes"] if BUILD_WORKFLOW_LOCK else (),
        comfy_cli_version=None if FORCE_LATEST else "1.16.0",
    )
    if BUILD_GPU_RUNTIME
    else []
)

runtime_image = None
if BUILD_GPU_RUNTIME:
    runtime_image = (
        modal.Image.from_registry(IMAGE_TAG)
        .entrypoint([])
        .apt_install("git", "ca-certificates")
        # Keep Ashley venv ahead of Modal-injected typing_extensions/pydantic.
        .run_commands(
            "/ComfyUI/venv/bin/python -m pip install -U 'typing_extensions>=4.14' 'pydantic>=2.11'"
        )
    )

    if BASE_NODES_ENABLED:
        # Copy the installer into the image before RUN steps that invoke it.
        # Modal does not support shell heredocs inside run_commands (Dockerfile parser).
        # force_build only when COMFY_LATEST=1; models are not part of this Image.
        runtime_image = (
            runtime_image
            .add_local_file(
                local_path=str(Path(__file__).resolve().parent / "base_nodes.py"),
                remote_path=INSTALLER_REMOTE_PATH,
                copy=True,
            )
            .run_commands(
                *build_base_nodes_commands(),
                secrets=APP_SECRETS,
                force_build=FORCE_LATEST,
            )
            # Some node requirements pull the PyPI `pathlib` backport, which shadows
            # stdlib pathlib and crashes Python 3.12 (`from collections import Sequence`).
            .run_commands(
                "set -eu; "
                "/ComfyUI/venv/bin/python3 -m pip uninstall -y pathlib pathlib2 enum34 typing || true; "
                "rm -f /ComfyUI/venv/lib/python3.*/site-packages/pathlib.py "
                "/ComfyUI/venv/lib/python3.*/site-packages/pathlib.pyc "
                "/ComfyUI/venv/lib/python3.*/site-packages/__pycache__/pathlib*.pyc"
            )
        )

    for node_command in node_commands:
        # GITHUB_TOKEN from APP_SECRETS is available only during the build and is
        # not baked into the resulting Image. Public repos work without it.
        runtime_image = runtime_image.run_commands(
            node_command,
            secrets=APP_SECRETS,
            force_build=FORCE_LATEST,
        )

    for registry_command in registry_node_commands:
        runtime_image = runtime_image.run_commands(
            registry_command,
            force_build=FORCE_LATEST,
        )

    if BUILD_WORKFLOW_LOCK:
        runtime_image = runtime_image.add_local_file(
            WORKFLOW_LOCK_SOURCE,
            remote_path=str(IMAGE_WORKFLOW_LOCK),
            copy=True,
        )

    runtime_image = (
        runtime_image
        .env(
            {
                "DISABLE_AUTOLAUNCH": "1",
                "DISABLE_SYNC": "1",
                "PYTHONUNBUFFERED": "1",
                "COMFY_NO_TELEMETRY": "1",
            }
        )
        # Modal 1.x no longer automounts arbitrary imported local modules.
        .add_local_python_source(
            "base_nodes",
            "recipes",
            "workflow_resolver",
            "comfy_engine",
            "modal_config",
            "storage",
        )
    )


# Model downloads run on CPU and write directly into the persistent Volume.
sync_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("aria2", "ca-certificates")
    .uv_pip_install("huggingface_hub[hf_xet]==1.27.0")
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
    .add_local_python_source(
        "base_nodes",
        "recipes",
        "workflow_resolver",
        "comfy_engine",
        "modal_config",
        "storage",
    )
)

SYNC_RETRIES = modal.Retries(
    max_retries=3,
    backoff_coefficient=2.0,
    initial_delay=2.0,
    max_delay=30.0,
)


def _commit_storage() -> None:
    models_vol.commit()
    workspace_vol.commit()


@app.function(
    image=sync_image,
    volumes=APP_VOLUMES,
    secrets=APP_SECRETS,
    timeout=6 * 60 * MINUTES,
    retries=SYNC_RETRIES,
    cpu=8.0,
    memory=16384,
    max_containers=1,
)
def sync_models(profile: str) -> dict:
    result = sync_profile_models(
        profile,
        WORKSPACE,
        storage_root=STORAGE_ROOT,
        workers=HYDRATE_WORKERS,
    )
    _commit_storage()
    return result


@app.function(
    image=sync_image,
    volumes=APP_VOLUMES,
    secrets=APP_SECRETS,
    timeout=6 * 60 * MINUTES,
    retries=SYNC_RETRIES,
    cpu=8.0,
    memory=16384,
    max_containers=1,
)
def sync_workflow(workflow_lock: dict) -> dict:
    result = sync_workflow_models(
        workflow_lock,
        WORKSPACE,
        storage_root=STORAGE_ROOT,
        workers=HYDRATE_WORKERS,
    )
    _commit_storage()
    return result


if BUILD_GPU_RUNTIME:
    @app.function(
        image=runtime_image,
        gpu=GPU,
        timeout=SETTINGS.ui_timeout_seconds,
        startup_timeout=SETTINGS.ui_startup_timeout_seconds,
        scaledown_window=SETTINGS.ui_scaledown_window_seconds,
        volumes=APP_VOLUMES,
        secrets=APP_SECRETS,
        max_containers=1,
    )
    @modal.concurrent(
        max_inputs=SETTINGS.ui_max_inputs,
        target_inputs=SETTINGS.ui_target_inputs,
    )
    @modal.web_server(
        port=COMFY_PORT,
        startup_timeout=SETTINGS.ui_startup_timeout_seconds,
        requires_proxy_auth=SETTINGS.ui_requires_proxy_auth,
    )
    def ui():
        if IMAGE_WORKFLOW_LOCK.is_file():
            workflow_lock = load_workflow_lock(IMAGE_WORKFLOW_LOCK, require_resolved=True)
            verify_workflow_models(
                workflow_lock,
                WORKSPACE,
                storage_root=STORAGE_ROOT,
            )
        prepare_runtime(COMFY_ROOT, WORKSPACE, STORAGE_ROOT)

        extra = tuple(shlex.split(os.environ.get("EXTRA_ARGS", "")))
        start_comfyui(
            profile_name=PROFILE_NAME,
            comfy_root=COMFY_ROOT,
            workspace=WORKSPACE,
            port=COMFY_PORT,
            extra_args=extra,
        )
        print(f"ComfyUI profile={PROFILE_NAME!r} starting on :{COMFY_PORT}")


@app.local_entrypoint()
def main(
    action: str = "info",
    profile: str = PROFILE_NAME,
    workflow: str = "",
    lock_out: str = "",
):
    """Local control entrypoint for profiles and CPU hydrate into Modal Storage."""
    action = action.strip().lower()

    if action == "profiles":
        for name, recipe in PROFILES.items():
            print(
                f"{name:22} "
                f"models={','.join(recipe.model_packs) or '-':24} "
                f"nodes={','.join(recipe.node_packs) or '-':24} "
                f"{recipe.description}"
            )
        return

    if action in {"sync", "hydrate"} and not workflow:
        get_profile(profile)  # validate before remote call
        result = sync_models.remote(profile)
        print(result)
        return

    if action == "resolve":
        if not workflow:
            raise ValueError("--workflow is required for action=resolve")
        output = lock_out or str(Path(workflow).with_suffix(".lock.json"))
        lock = write_workflow_lock(workflow, output)
        print(
            {
                "lock": output,
                "models": len(lock["models"]),
                "custom_nodes": len(lock["custom_nodes"]),
                "unresolved": lock["unresolved"],
            }
        )
        return

    if action in {"workflow-sync", "hydrate"}:
        if not workflow:
            raise ValueError("--workflow is required for action=workflow-sync / hydrate")
        output = lock_out or str(Path(workflow).with_suffix(".lock.json"))
        lock = write_workflow_lock(workflow, output)
        validate_workflow_lock(lock, require_resolved=True)
        result = sync_workflow.remote(lock)
        print({**result, "lock": output})
        return

    if action != "info":
        raise ValueError(
            "action must be one of: info, profiles, hydrate, sync, resolve, workflow-sync"
        )

    print(
        f"""
App:       {APP_NAME}
Image:     {IMAGE_TAG}
Profile:   {PROFILE_NAME}
GPU:       {GPU}
Port:      {COMFY_PORT}
Workspace: {SETTINGS.volume_name} -> {WORKSPACE}
Storage:   {SETTINGS.models_volume_name} -> {STORAGE_ROOT}
Workers:   {HYDRATE_WORKERS}
Secret:    {SECRET_NAME}
Workflow:  {WORKFLOW_LOCK_SOURCE or '(none)'}
BaseNodes: {BASE_NODES_ENABLED}
Latest:    {FORCE_LATEST}
ProxyAuth: {SETTINGS.ui_requires_proxy_auth}

1. List profiles:
   modal run comfyui_modal.py --action profiles

2. Hydrate models into Modal Storage (CPU, no GPU):
   modal run comfyui_modal.py --action hydrate --profile qwen-image
   modal run comfyui_modal.py --action hydrate --workflow examples/z-image-base.json

3. Resolve a workflow without downloading:
   modal run comfyui_modal.py --action resolve --workflow workflow.json

4. Interactive UI (cached Image unless COMFY_LATEST=1):
   python -m pip install -U modal
   COMFY_PROFILE=qwen-image modal serve comfyui_modal.py

5. Persistent endpoint:
   COMFY_PROFILE=qwen-image COMFY_WORKFLOW_LOCK=workflow.lock.json modal deploy comfyui_modal.py

Optional:
   MODAL_GPU=L4 COMFY_BASE_NODES=0 modal serve comfyui_modal.py
   COMFY_LATEST=1 modal serve comfyui_modal.py
   EXTRA_ARGS='--lowvram' COMFY_PROFILE=qwen-image modal serve comfyui_modal.py
   COMFY_HYDRATE_WORKERS=8 modal run comfyui_modal.py --action hydrate --workflow workflow.json
""".strip()
    )
