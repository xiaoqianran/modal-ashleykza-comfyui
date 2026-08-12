"""Deploy ashleykleynhans/comfyui on Modal with declarative recipes.

Architecture:
- Image: Ashley runtime + pinned 130-node GitHub base (from CNB nodes.md) + small profile extras.
- Volume: models / input / output / user / optional user nodes / logs / lock state.
- CPU sync function: downloads models without paying for GPU time.
- GPU web server: only prepares paths and starts ComfyUI.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

import modal

from base_nodes import (
    BASE_NODE_COUNT,
    BASE_NODES_IMAGE,
    INSTALLER_REMOTE_PATH,
    build_base_nodes_commands,
)
from comfy_engine import build_node_commands, prepare_runtime, start_comfyui, sync_profile_models
from recipes import PROFILES, get_profile


APP_NAME = "comfyui-ashleykza-cu128"
IMAGE_TAG = os.getenv(
    "COMFY_IMAGE",
    "ghcr.io/ashleykleynhans/comfyui:cu128-py312-v0.32.0",
)
COMFY_ROOT = Path("/ComfyUI")
WORKSPACE = Path("/workspace")
COMFY_PORT = 3001
MINUTES = 60

PROFILE_NAME = os.getenv("COMFY_PROFILE", "base").strip() or "base"
PROFILE = get_profile(PROFILE_NAME)

GPU_DEFAULT = ["T4", "L4", "L40S", "RTX-PRO-6000"]
gpu_env = os.getenv("MODAL_GPU", "").strip()
GPU = [item.strip() for item in gpu_env.split(",") if item.strip()] if gpu_env else GPU_DEFAULT

BASE_NODES_ENABLED = os.getenv("COMFY_BASE_NODES", "1").strip().lower() not in {"0", "false", "no", "off"}

# Always use a named Modal Secret so local/remote dependency graphs match.
# Conditional from_dotenv(.env) breaks hydration: .env exists locally but not
# inside the remote container, so Modal sees 2 deps locally vs 3 object ids.
SECRET_NAME = os.getenv("MODAL_SECRET_NAME", "comfyui-creds").strip() or "comfyui-creds"
APP_SECRETS = [modal.Secret.from_name(SECRET_NAME)]

app = modal.App(APP_NAME)
workspace_vol = modal.Volume.from_name(
    "comfyui-ashleykza-workspace",
    create_if_missing=True,
)

# Keep the expensive common base before profile-specific layers so Modal can
# cache it across profiles and normal redeploys.
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
    # GITHUB_TOKEN is exposed only for the clone RUN (same askpass pattern as extra nodes).
    runtime_image = (
        runtime_image
        .add_local_file(
            local_path=str(Path(__file__).resolve().parent / "base_nodes.py"),
            remote_path=INSTALLER_REMOTE_PATH,
            copy=True,
        )
        .run_commands(*build_base_nodes_commands(), secrets=APP_SECRETS)
    )

extra_node_commands = build_node_commands(PROFILE.node_packs)
if extra_node_commands:
    # GITHUB_TOKEN is only exposed during these image-build commands. The
    # command builder configures askpass before enabling shell xtrace.
    runtime_image = runtime_image.run_commands(*extra_node_commands, secrets=APP_SECRETS)

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
    .add_local_python_source("base_nodes", "recipes", "comfy_engine")
)

# Model downloads run on CPU and write directly into the persistent Volume.
sync_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("aria2", "ca-certificates")
    .uv_pip_install("huggingface_hub==1.24.0")
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
    .add_local_python_source("recipes", "comfy_engine")
)


@app.function(
    image=sync_image,
    volumes={str(WORKSPACE): workspace_vol},
    secrets=APP_SECRETS,
    timeout=6 * 60 * MINUTES,
    max_containers=1,
)
def sync_models(profile: str) -> dict:
    result = sync_profile_models(profile, WORKSPACE)
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
def main(action: str = "info", profile: str = PROFILE_NAME):
    """Local control entrypoint. action: info | profiles | sync"""
    action = action.strip().lower()

    if action == "profiles":
        for name, recipe in PROFILES.items():
            print(
                f"{name:22} "
                f"models={','.join(recipe.model_packs) or '-':24} "
                f"extra_nodes={','.join(recipe.node_packs) or '-':28} "
                f"{recipe.description}"
            )
        return

    if action == "sync":
        get_profile(profile)
        print(sync_models.remote(profile))
        return

    if action != "info":
        raise ValueError("action must be one of: info, profiles, sync")

    print(
        f"""
App:         {APP_NAME}
Image:       {IMAGE_TAG}
Profile:     {PROFILE_NAME}
GPU:         {GPU}
Port:        {COMFY_PORT}
Base nodes:  {BASE_NODE_COUNT if BASE_NODES_ENABLED else 0} (GitHub clones from {BASE_NODES_IMAGE}; default ON / COMFY_BASE_NODES=1)
Volume:      comfyui-ashleykza-workspace
Secret:      {SECRET_NAME}

List profiles:
  modal run comfyui_modal.py --action profiles

Sync models without GPU:
  modal run comfyui_modal.py --action sync --profile qwen-image

Interactive UI (base nodes ON by default; omit COMFY_BASE_NODES):
  COMFY_PROFILE=qwen-image modal serve comfyui_modal.py

Persistent endpoint:
  COMFY_PROFILE=qwen-image modal deploy comfyui_modal.py

Debug only — temporarily disable common base nodes:
  COMFY_BASE_NODES=0 COMFY_PROFILE=qwen-image modal serve comfyui_modal.py
""".strip()
    )
