"""Deploy ashleykleynhans/comfyui on Modal with declarative recipes.

Architecture:
- Image: immutable ComfyUI runtime + selected stable custom nodes.
- Volume: models / input / output / user / optional user nodes / logs / lock state.
- CPU sync function: downloads models without paying for GPU time.
- GPU web server: only prepares paths and starts ComfyUI.

Examples:
    modal run comfyui_modal.py --action profiles
    modal run comfyui_modal.py --action sync --profile qwen-image
    modal run comfyui_modal.py --action resolve --workflow workflow.json
    modal run comfyui_modal.py --action workflow-sync --workflow workflow.json

    COMFY_PROFILE=qwen-image modal serve comfyui_modal.py
    COMFY_PROFILE=qwen-image modal deploy comfyui_modal.py
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

import modal

from comfy_engine import (
    build_node_commands,
    build_registry_node_commands,
    prepare_runtime,
    start_comfyui,
    sync_profile_models,
    sync_workflow_models,
    verify_workflow_models,
)
from recipes import PROFILES, get_profile
from workflow_resolver import (
    load_workflow_lock,
    validate_workflow_lock,
    write_workflow_lock,
)


APP_NAME = "comfyui-ashleykza-cu128"
IMAGE_TAG = os.getenv(
    "COMFY_IMAGE",
    "ghcr.io/ashleykleynhans/comfyui:cu128-py312-v0.32.0",
)
COMFY_ROOT = Path("/ComfyUI")
WORKSPACE = Path("/workspace")
COMFY_PORT = 3001
MINUTES = 60
IMAGE_WORKFLOW_LOCK = Path("/opt/comfy/workflow.lock.json")

PROFILE_NAME = os.getenv("COMFY_PROFILE", "base").strip() or "base"
PROFILE = get_profile(PROFILE_NAME)
WORKFLOW_LOCK_SOURCE = os.getenv("COMFY_WORKFLOW_LOCK", "").strip()
BUILD_WORKFLOW_LOCK = (
    load_workflow_lock(WORKFLOW_LOCK_SOURCE, require_resolved=True)
    if WORKFLOW_LOCK_SOURCE and modal.is_local()
    else None
)

GPU_DEFAULT = ["L4", "L40S", "RTX-PRO-6000"]
gpu_env = os.getenv("MODAL_GPU", "").strip()
GPU = [item.strip() for item in gpu_env.split(",") if item.strip()] if gpu_env else GPU_DEFAULT

SECRET_NAME = os.getenv("MODAL_SECRET_NAME", "").strip()
DOTENV_PATH = Path(".env")

# Secret priority:
#   1) named Modal Secret (best for shared/prod deployments)
#   2) local .env (best for personal development; never commit it)
if SECRET_NAME:
    APP_SECRETS = [modal.Secret.from_name(SECRET_NAME)]
elif DOTENV_PATH.is_file():
    APP_SECRETS = [modal.Secret.from_dotenv(str(DOTENV_PATH))]
else:
    APP_SECRETS = []

app = modal.App(APP_NAME)
workspace_vol = modal.Volume.from_name(
    "comfyui-ashleykza-workspace",
    create_if_missing=True,
)


# Stable profile nodes and workflow-declared CNR nodes are installed in CPU Image builds.
node_commands = build_node_commands(PROFILE.node_packs)
registry_node_commands = build_registry_node_commands(
    BUILD_WORKFLOW_LOCK["custom_nodes"] if BUILD_WORKFLOW_LOCK else ()
)

runtime_image = (
    modal.Image.from_registry(IMAGE_TAG)
    .entrypoint([])
    .apt_install("git")
)

for node_command in node_commands:
    # GITHUB_TOKEN from APP_SECRETS is available only during the build and is
    # not baked into the resulting Image. Public repos work without it.
    runtime_image = runtime_image.run_commands(node_command, secrets=APP_SECRETS)

for registry_command in registry_node_commands:
    runtime_image = runtime_image.run_commands(registry_command)

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
        }
    )
    # Modal 1.x no longer automounts arbitrary imported local modules.
    .add_local_python_source("recipes", "workflow_resolver", "comfy_engine")
)


# Model downloads run on CPU and write directly into the persistent Volume.
sync_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("aria2", "ca-certificates")
    .uv_pip_install("huggingface_hub[hf_xet]==1.27.0")
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
    .add_local_python_source("recipes", "workflow_resolver", "comfy_engine")
)

SYNC_RETRIES = modal.Retries(
    max_retries=3,
    backoff_coefficient=2.0,
    initial_delay=2.0,
    max_delay=30.0,
)


@app.function(
    image=sync_image,
    volumes={str(WORKSPACE): workspace_vol},
    secrets=APP_SECRETS,
    timeout=6 * 60 * MINUTES,
    retries=SYNC_RETRIES,
    cpu=2.0,
    memory=2048,
    max_containers=1,
)
def sync_models(profile: str) -> dict:
    result = sync_profile_models(profile, WORKSPACE)
    workspace_vol.commit()
    return result


@app.function(
    image=sync_image,
    volumes={str(WORKSPACE): workspace_vol},
    secrets=APP_SECRETS,
    timeout=6 * 60 * MINUTES,
    retries=SYNC_RETRIES,
    cpu=2.0,
    memory=2048,
    max_containers=1,
)
def sync_workflow(workflow_lock: dict) -> dict:
    result = sync_workflow_models(workflow_lock, WORKSPACE)
    workspace_vol.commit()
    return result


@app.function(
    image=runtime_image,
    gpu=GPU,
    timeout=60 * MINUTES,
    scaledown_window=5 * MINUTES,
    volumes={str(WORKSPACE): workspace_vol},
    secrets=APP_SECRETS,
    max_containers=1,
)
@modal.concurrent(max_inputs=20)
@modal.web_server(port=COMFY_PORT, startup_timeout=15 * MINUTES)
def ui():
    if IMAGE_WORKFLOW_LOCK.is_file():
        workflow_lock = load_workflow_lock(IMAGE_WORKFLOW_LOCK, require_resolved=True)
        verify_workflow_models(workflow_lock, WORKSPACE)
    prepare_runtime(COMFY_ROOT, WORKSPACE)

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
    """Local control entrypoint for profiles and workflow dependency prefetching."""
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

    if action == "sync":
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

    if action == "workflow-sync":
        if not workflow:
            raise ValueError("--workflow is required for action=workflow-sync")
        output = lock_out or str(Path(workflow).with_suffix(".lock.json"))
        lock = write_workflow_lock(workflow, output)
        validate_workflow_lock(lock, require_resolved=True)
        result = sync_workflow.remote(lock)
        print({**result, "lock": output})
        return

    if action != "info":
        raise ValueError("action must be one of: info, profiles, sync, resolve, workflow-sync")

    print(
        f"""
App:       {APP_NAME}
Image:     {IMAGE_TAG}
Profile:   {PROFILE_NAME}
GPU:       {GPU}
Port:      {COMFY_PORT}
Volume:    comfyui-ashleykza-workspace
Secret:    {SECRET_NAME or ('.env' if DOTENV_PATH.is_file() else '(none)')}
Workflow:  {WORKFLOW_LOCK_SOURCE or '(none)'}

1. List profiles:
   modal run comfyui_modal.py --action profiles

2. Sync models without GPU:
   modal run comfyui_modal.py --action sync --profile qwen-image

3. Resolve and sync a workflow without GPU:
   modal run comfyui_modal.py --action resolve --workflow workflow.json
   modal run comfyui_modal.py --action workflow-sync --workflow workflow.json

4. Interactive UI:
   COMFY_PROFILE=qwen-image modal serve comfyui_modal.py

5. Persistent endpoint:
   COMFY_PROFILE=qwen-image COMFY_WORKFLOW_LOCK=workflow.lock.json modal deploy comfyui_modal.py

Optional:
   MODAL_GPU=L40S COMFY_PROFILE=wan22 modal serve comfyui_modal.py
   EXTRA_ARGS='--lowvram' COMFY_PROFILE=qwen-image modal serve comfyui_modal.py
   MODAL_SECRET_NAME=comfyui-secrets COMFY_PROFILE=nordy-kontext-views modal deploy comfyui_modal.py
""".strip()
    )
