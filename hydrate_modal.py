"""CPU-only hydrate into Modal Storage.

Two launch modes (plugins are parsed, never installed here):

    modal run hydrate_modal.py --workflow examples/z-image-base.json
    modal run hydrate_modal.py --profile qwen-image

GPU serve/deploy stays in ``comfyui_modal.py``. This App does not build the
GPU Image or clone custom nodes. The active lock is written to Volume
``.state/launch.json`` so the GPU Image can stay cached across workflows.
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


def _launch(
    *,
    profile: str,
    workflow: str,
    lock_out: str,
    install_nodes: bool,
    skip_lock_nodes: bool,
) -> ModalSettings:
    env = dict(os.environ)
    if workflow.strip():
        env["COMFY_WORKFLOW"] = workflow.strip()
    elif profile.strip():
        env.pop("COMFY_WORKFLOW", None)
    if profile.strip():
        env["COMFY_PROFILE"] = profile.strip()
    if lock_out.strip():
        env["COMFY_WORKFLOW_LOCK"] = lock_out.strip()
    if install_nodes:
        env["COMFY_INSTALL_NODES"] = "1"
    if skip_lock_nodes:
        env["COMFY_INSTALL_LOCK_NODES"] = "0"
    return ModalSettings.from_env(env)


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
def sync_workflow(
    workflow_lock: dict,
    install_lock_nodes: bool = True,
    workflow_source: str = "",
    lock_source: str = "",
    profile_name: str = "base",
) -> dict:
    result = sync_workflow_models(
        workflow_lock,
        WORKSPACE,
        storage_root=STORAGE_ROOT,
        workers=HYDRATE_WORKERS,
        install_lock_nodes=install_lock_nodes,
        workflow_source=workflow_source,
        lock_source=lock_source,
        profile_name=profile_name,
    )
    _commit_storage()
    return result


def _hydrate_workflow(settings: ModalSettings) -> dict:
    lock = write_workflow_lock(settings.workflow_source, settings.workflow_lock_source)
    validate_workflow_lock(lock, require_resolved=True)
    plugins = lock["custom_nodes"]
    result = {
        **sync_workflow.remote(
            lock,
            settings.install_lock_nodes,
            settings.workflow_source,
            settings.workflow_lock_source,
            settings.profile_name,
        ),
        "mode": "workflow",
        "workflow": settings.workflow_source,
        "lock": settings.workflow_lock_source,
        "plugins_parsed": [
            {"id": node.get("id"), "version": node.get("version")} for node in plugins
        ],
        "plugins_downloaded": 0,
        "plugins_note": (
            "custom nodes recorded in Volume .state/launch.json; GPU start "
            "installs them into /workspace/custom_nodes (skip if present). "
            "The GPU Image is not rebuilt."
        ),
    }
    return result


def _hydrate_profile(settings: ModalSettings) -> dict:
    get_profile(settings.profile_name)
    return {
        **sync_models.remote(settings.profile_name),
        "mode": "profile",
        "profile": settings.profile_name,
        "plugins_installed": 0,
        "plugins_note": (
            "profile node packs stay off. Opt in with COMFY_INSTALL_NODES=1 "
            "on serve/deploy (that does change the GPU Image)."
        ),
    }


@app.local_entrypoint()
def main(
    action: str = "hydrate",
    profile: str = "",
    workflow: str = "",
    lock_out: str = "",
    install_nodes: bool = False,
    skip_lock_nodes: bool = False,
):
    """Hydrate models. ``--workflow`` or ``--profile``; plugins are not installed here."""
    action = action.strip().lower()
    settings = _launch(
        profile=profile,
        workflow=workflow,
        lock_out=lock_out,
        install_nodes=install_nodes,
        skip_lock_nodes=skip_lock_nodes,
    )

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
        if settings.launch_mode != "workflow":
            raise ValueError("--workflow is required for action=resolve")
        lock = write_workflow_lock(settings.workflow_source, settings.workflow_lock_source)
        print(
            {
                "mode": "workflow",
                "lock": settings.workflow_lock_source,
                "models": len(lock["models"]),
                "custom_nodes": lock["custom_nodes"],
                "unresolved": lock["unresolved"],
                "plugins_installed": False,
                "plugins_note": (
                    "lock custom_nodes are installed onto the workspace Volume "
                    "at GPU start, not into the Image"
                ),
            }
        )
        return

    if action in {"hydrate", "sync", "workflow-sync"}:
        if settings.launch_mode == "workflow":
            print(_hydrate_workflow(settings))
            return
        print(_hydrate_profile(settings))
        return

    if action != "info":
        raise ValueError("action must be one of: info, profiles, hydrate, sync, resolve, workflow-sync")

    print(
        f"""
App:     {APP_NAME}
Mode:    {settings.launch_mode}
Storage: {SETTINGS.models_volume_name} -> {STORAGE_ROOT}
Workers: {HYDRATE_WORKERS}

# workflow JSON: parse models + plugins, download models only
modal run hydrate_modal.py --workflow examples/z-image-base.json

# named profile: download that profile's model packs
modal run hydrate_modal.py --profile qwen-image

# GPU UI (same cached Image; lock CNR on workspace Volume)
MODAL_GPU=T4 modal serve comfyui_modal.py
COMFY_PROFILE=qwen-image MODAL_GPU=T4 modal serve comfyui_modal.py
""".strip()
    )
