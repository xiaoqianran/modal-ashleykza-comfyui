"""CPU-only hydrate into Modal Storage.

This App does not register the GPU ComfyUI Image, so ``modal run`` will not
clone GitHub node packs. GPU serve/deploy stays in ``comfyui_modal.py``.

The models Volume layout matches ComfyUI ``models/<category>/``:

    /mnt/comfy-storage/vae/ae.safetensors
    /mnt/comfy-storage/text_encoders/qwen_3_4b.safetensors
    /mnt/comfy-storage/diffusion_models/z_image_bf16.safetensors

Examples:
    modal run hydrate_modal.py --action hydrate --profile qwen-image
    modal run hydrate_modal.py --action hydrate --workflow examples/z-image-base.json
    modal run hydrate_modal.py --action resolve --workflow workflow.json
"""

from __future__ import annotations

import os
from pathlib import Path

import modal

from comfy_engine import sync_profile_models, sync_workflow_models
from modal_config import ModalSettings
from recipes import PROFILES, get_profile
from workflow_resolver import validate_workflow_lock, write_workflow_lock

SETTINGS = ModalSettings.from_env(os.environ)
APP_NAME = f"{SETTINGS.app_name}-hydrate"
WORKSPACE = Path("/workspace")
STORAGE_ROOT = Path(SETTINGS.storage_root)
HYDRATE_WORKERS = SETTINGS.hydrate_workers
MINUTES = 60
SECRET_NAME = SETTINGS.secret_name
APP_SECRETS = [modal.Secret.from_name(SECRET_NAME)]

app = modal.App(APP_NAME)
workspace_vol = modal.Volume.from_name(SETTINGS.volume_name, create_if_missing=True)
models_vol = modal.Volume.from_name(SETTINGS.models_volume_name, create_if_missing=True)
APP_VOLUMES = {
    str(WORKSPACE): workspace_vol,
    str(STORAGE_ROOT): models_vol,
}

sync_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("aria2", "ca-certificates")
    .uv_pip_install("huggingface_hub[hf_xet]==1.27.0")
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
    .add_local_python_source(
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


@app.local_entrypoint()
def main(
    action: str = "hydrate",
    profile: str = SETTINGS.profile_name,
    workflow: str = "",
    lock_out: str = "",
):
    """Download models into Modal Storage without building the GPU Image."""
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

    if action in {"sync", "hydrate"} and not workflow:
        get_profile(profile)
        print(sync_models.remote(profile))
        return

    if action in {"hydrate", "workflow-sync", "sync"}:
        if not workflow:
            raise ValueError("--workflow is required to hydrate a workflow")
        output = lock_out or str(Path(workflow).with_suffix(".lock.json"))
        lock = write_workflow_lock(workflow, output)
        validate_workflow_lock(lock, require_resolved=True)
        print({**sync_workflow.remote(lock), "lock": output})
        return

    if action != "info":
        raise ValueError("action must be one of: info, profiles, hydrate, sync, resolve, workflow-sync")

    print(
        f"""
App:     {APP_NAME}
Storage: {SETTINGS.models_volume_name} -> {STORAGE_ROOT}
Workers: {HYDRATE_WORKERS}

modal run hydrate_modal.py --action hydrate --workflow examples/z-image-base.json
modal run hydrate_modal.py --action hydrate --profile qwen-image
COMFY_BASE_NODES=0 MODAL_GPU=L4 modal serve comfyui_modal.py
""".strip()
    )
