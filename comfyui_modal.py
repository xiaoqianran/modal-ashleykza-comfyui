"""Deploy ashleykleynhans/comfyui on Modal.

Launch modes (set env or pass the same flags used by hydrate):

    COMFY_WORKFLOW=examples/z-image-base.json modal serve comfyui_modal.py
    COMFY_PROFILE=qwen-image modal serve comfyui_modal.py

Custom nodes from a workflow lock are installed on the GPU Image.
The 130 GitHub base clones and profile extra packs stay off unless
``COMFY_BASE_NODES=1`` / ``COMFY_INSTALL_NODES=1``. Hydrate models
with ``hydrate_modal.py``.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import modal

from base_nodes import INSTALLER_REMOTE_PATH, build_base_nodes_commands
from comfy_engine import (
    build_node_commands,
    build_registry_node_commands,
    prepare_runtime,
    start_comfyui,
    verify_workflow_models,
    wait_comfyui_ready,
)
from modal_config import ModalSettings
from recipes import get_profile
from workflow_resolver import load_workflow_lock, write_workflow_lock

SETTINGS = ModalSettings.from_env(os.environ, sys.argv)
APP_NAME = SETTINGS.app_name
IMAGE_TAG = SETTINGS.image_tag
COMFY_ROOT = Path("/ComfyUI")
WORKSPACE = Path("/workspace")
STORAGE_ROOT = Path(SETTINGS.storage_root)
COMFY_PORT = 3001
IMAGE_WORKFLOW_LOCK = Path("/opt/comfy/workflow.lock.json")

PROFILE_NAME = SETTINGS.profile_name
PROFILE = get_profile(PROFILE_NAME)
FORCE_LATEST = SETTINGS.latest_dependencies
BASE_NODES_ENABLED = SETTINGS.base_nodes_enabled
INSTALL_LOCK_NODES = SETTINGS.install_lock_nodes
INSTALL_NODES = SETTINGS.install_nodes

if SETTINGS.workflow_source and modal.is_local():
    BUILD_WORKFLOW_LOCK = write_workflow_lock(
        SETTINGS.workflow_source,
        SETTINGS.workflow_lock_source,
    )
    WORKFLOW_LOCK_SOURCE = SETTINGS.workflow_lock_source
elif SETTINGS.workflow_lock_source and modal.is_local():
    WORKFLOW_LOCK_SOURCE = SETTINGS.workflow_lock_source
    BUILD_WORKFLOW_LOCK = load_workflow_lock(
        WORKFLOW_LOCK_SOURCE,
        require_resolved=True,
    )
else:
    WORKFLOW_LOCK_SOURCE = SETTINGS.workflow_lock_source
    BUILD_WORKFLOW_LOCK = None

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


# Workflow-lock CNR nodes are required by the JSON. Profile extras stay opt-in.
node_commands = (
    build_node_commands(PROFILE.node_packs) if INSTALL_NODES else ()
)
registry_node_commands = (
    build_registry_node_commands(
        BUILD_WORKFLOW_LOCK["custom_nodes"] if BUILD_WORKFLOW_LOCK else (),
        comfy_cli_version=None if FORCE_LATEST else "1.16.0",
    )
    if INSTALL_LOCK_NODES
    else ()
)

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
            "TORCHINDUCTOR_COMPILE_THREADS": "1",
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


UI_CLS_KWARGS: dict = {
    "image": runtime_image,
    "gpu": GPU,
    "timeout": SETTINGS.ui_timeout_seconds,
    "startup_timeout": SETTINGS.ui_startup_timeout_seconds,
    "scaledown_window": SETTINGS.ui_scaledown_window_seconds,
    "volumes": APP_VOLUMES,
    "secrets": APP_SECRETS,
    "max_containers": 1,
    "enable_memory_snapshot": SETTINGS.memory_snapshot,
}
if SETTINGS.gpu_snapshot:
    UI_CLS_KWARGS["experimental_options"] = {"enable_gpu_snapshot": True}


@app.cls(**UI_CLS_KWARGS)
@modal.concurrent(
    max_inputs=SETTINGS.ui_max_inputs,
    target_inputs=SETTINGS.ui_target_inputs,
)
class UI:
    """ComfyUI web server. Memory snapshots are created after ``modal deploy``.

    ``modal serve`` still starts the same Cls but does not persist snapshots.
    """

    @modal.enter(snap=True)
    def start(self):
        if IMAGE_WORKFLOW_LOCK.is_file():
            workflow_lock = load_workflow_lock(IMAGE_WORKFLOW_LOCK, require_resolved=True)
            verify_workflow_models(
                workflow_lock,
                WORKSPACE,
                storage_root=STORAGE_ROOT,
            )
        prepare_runtime(COMFY_ROOT, WORKSPACE, STORAGE_ROOT)
        extra = tuple(shlex.split(os.environ.get("EXTRA_ARGS", "")))
        self.process = start_comfyui(
            profile_name=PROFILE_NAME,
            comfy_root=COMFY_ROOT,
            workspace=WORKSPACE,
            port=COMFY_PORT,
            extra_args=extra,
        )
        wait_comfyui_ready(port=COMFY_PORT, timeout=SETTINGS.ui_startup_timeout_seconds)
        print(
            f"ComfyUI mode={SETTINGS.launch_mode!r} profile={PROFILE_NAME!r} "
            f"lock_nodes={INSTALL_LOCK_NODES} extra_nodes={INSTALL_NODES} "
            f"ready on :{COMFY_PORT}"
        )

    @modal.web_server(
        port=COMFY_PORT,
        startup_timeout=SETTINGS.ui_startup_timeout_seconds,
        requires_proxy_auth=SETTINGS.ui_requires_proxy_auth,
    )
    def ui(self):
        pass

    @modal.exit()
    def stop(self):
        process = getattr(self, "process", None)
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
        except OSError:
            return


@app.local_entrypoint()
def main():
    """Print launch configuration. Hydrate with hydrate_modal.py."""
    print(
        f"""
App:       {APP_NAME}
Mode:      {SETTINGS.launch_mode}
Image:     {IMAGE_TAG}
Profile:   {PROFILE_NAME}
Workflow:  {SETTINGS.workflow_source or WORKFLOW_LOCK_SOURCE or '(none)'}
GPU:       {GPU}
Port:      {COMFY_PORT}
Workspace: {SETTINGS.volume_name} -> {WORKSPACE}
Storage:   {SETTINGS.models_volume_name} -> {STORAGE_ROOT}
Secret:    {SECRET_NAME}
InstallLockNodes: {INSTALL_LOCK_NODES}
InstallExtraNodes: {INSTALL_NODES}
BaseNodes: {BASE_NODES_ENABLED}
Latest:    {FORCE_LATEST}
Snapshot:  memory={SETTINGS.memory_snapshot} gpu={SETTINGS.gpu_snapshot}

# 1. Hydrate models (CPU)
modal run hydrate_modal.py --workflow examples/z-image-base.json
modal run hydrate_modal.py --profile qwen-image

# 2. GPU UI (lock CNR nodes on; 130 clones / profile extras off)
COMFY_WORKFLOW=examples/z-image-base.json MODAL_GPU=T4 modal serve comfyui_modal.py
COMFY_PROFILE=qwen-image MODAL_GPU=T4 modal deploy comfyui_modal.py
""".strip()
    )
