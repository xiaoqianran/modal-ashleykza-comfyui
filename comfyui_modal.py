"""Deploy ashleykleynhans/comfyui on Modal.

The GPU Image is workflow-agnostic so Modal can cache it. Hydrate writes the
active lock to Volume ``.state/launch.json``; GPU start installs lock CNR
nodes into ``/workspace/custom_nodes`` (skip if already present).

    modal run hydrate_modal.py --workflow examples/z-image-base.json
    modal serve comfyui_modal.py

The 130 GitHub base clones and profile extra packs stay off unless
``COMFY_BASE_NODES=1`` / ``COMFY_INSTALL_NODES=1`` (those do change the Image).
"""

from __future__ import annotations

import os
import shlex
import sys
import threading
from pathlib import Path

import modal

from base_nodes import INSTALLER_REMOTE_PATH, build_base_nodes_commands
from comfy_engine import (
    apply_volume_launch,
    build_node_commands,
    output_manifest,
    stop_comfyui,
)
from modal_config import ModalSettings
from recipes import get_profile
from storage import workspace_dir

SETTINGS = ModalSettings.from_env(os.environ, sys.argv)
APP_NAME = SETTINGS.app_name
IMAGE_TAG = SETTINGS.image_tag
COMFY_ROOT = Path("/ComfyUI")
WORKSPACE = Path("/workspace")
STORAGE_ROOT = Path(SETTINGS.storage_root)
COMFY_PORT = 3001

PROFILE_NAME = SETTINGS.profile_name
PROFILE = get_profile(PROFILE_NAME)
FORCE_LATEST = SETTINGS.latest_dependencies
BASE_NODES_ENABLED = SETTINGS.base_nodes_enabled
INSTALL_LOCK_NODES = SETTINGS.install_lock_nodes
INSTALL_NODES = SETTINGS.install_nodes

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


# Profile extras stay opt-in Image layers. Workflow-lock CNR is Volume-backed.
node_commands = (
    build_node_commands(PROFILE.node_packs) if INSTALL_NODES else ()
)

runtime_image = (
    modal.Image.from_registry(IMAGE_TAG)
    .entrypoint([])
    # cmake/ninja are required when lock CNR packs (Pixal3D) compile natten / CUDA extensions.
    .apt_install(
        "git",
        "ca-certificates",
        "cmake",
        "ninja-build",
        "build-essential",
        "python3-dev",
    )
    # Keep Ashley venv ahead of Modal-injected typing_extensions/pydantic.
    .run_commands(
        "/ComfyUI/venv/bin/python -m pip install -U 'typing_extensions>=4.14' 'pydantic>=2.11'"
    )
    # Stable for every workflow; runtime lock-CNR install uses this binary.
    .run_commands(
        "/ComfyUI/venv/bin/python -m pip install --no-cache-dir 'comfy-cli==1.16.0'"
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


def _commit_workspace_output(reason: str) -> None:
    workspace_vol.commit()
    print(f"Committed workspace Volume ({reason})", flush=True)


def start_output_commit_watch(
    output_dir: Path,
    *,
    interval: float = 2.0,
) -> tuple[threading.Event, threading.Thread]:
    """Commit ``/workspace/output`` when SaveVideo writes, so 5s GPU scaledown keeps files."""
    stop = threading.Event()
    last = output_manifest(output_dir)

    def loop() -> None:
        nonlocal last
        while not stop.wait(interval):
            try:
                current = output_manifest(output_dir)
                if current != last:
                    _commit_workspace_output("output changed")
                    last = current
            except Exception as exc:  # noqa: BLE001
                print(f"workspace output commit skipped: {exc}", flush=True)

    thread = threading.Thread(target=loop, name="workspace-output-commit", daemon=True)
    thread.start()
    return stop, thread


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
    def snapshot_runtime(self):
        """Image-local + current Volume launch, captured by memory snapshot."""
        extra = tuple(shlex.split(os.environ.get("EXTRA_ARGS", "")))
        self.process, self._launch_fingerprint, newly = apply_volume_launch(
            storage_root=STORAGE_ROOT,
            workspace=WORKSPACE,
            comfy_root=COMFY_ROOT,
            default_profile=PROFILE_NAME,
            default_install_lock_nodes=INSTALL_LOCK_NODES,
            extra_args=extra,
            port=COMFY_PORT,
            startup_timeout=SETTINGS.ui_startup_timeout_seconds,
        )
        if newly:
            workspace_vol.commit()
        print(
            f"ComfyUI snapshot fingerprint={self._launch_fingerprint} "
            f"ready on :{COMFY_PORT}",
            flush=True,
        )

    @modal.enter(snap=False)
    def apply_launch(self):
        """Re-read Volumes after restore so hydrate can change launch.json.

        ``Volume.reload()`` fails if ComfyUI still holds workspace files open
        (``logs/comfyui.log``). Stop the server first; ``apply_volume_launch``
        starts it again after the reload.
        """
        stop_comfyui(getattr(self, "process", None))
        self.process = None
        models_vol.reload()
        workspace_vol.reload()
        extra = tuple(shlex.split(os.environ.get("EXTRA_ARGS", "")))
        self.process, self._launch_fingerprint, newly = apply_volume_launch(
            storage_root=STORAGE_ROOT,
            workspace=WORKSPACE,
            comfy_root=COMFY_ROOT,
            default_profile=PROFILE_NAME,
            default_install_lock_nodes=INSTALL_LOCK_NODES,
            extra_args=extra,
            port=COMFY_PORT,
            startup_timeout=SETTINGS.ui_startup_timeout_seconds,
        )
        if newly:
            workspace_vol.commit()
        self._output_commit_stop, self._output_commit_thread = start_output_commit_watch(
            workspace_dir(WORKSPACE, "output")
        )
        print(
            f"ComfyUI launch applied fingerprint={self._launch_fingerprint} "
            f"lock_nodes={INSTALL_LOCK_NODES} extra_nodes={INSTALL_NODES} "
            f"ready on :{COMFY_PORT}",
            flush=True,
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
        stop_event = getattr(self, "_output_commit_stop", None)
        if stop_event is not None:
            stop_event.set()
        try:
            _commit_workspace_output("gpu exit")
        except Exception as exc:  # noqa: BLE001
            print(f"workspace commit on exit skipped: {exc}", flush=True)
        stop_comfyui(getattr(self, "process", None))


@app.local_entrypoint()
def main():
    """Print launch configuration. Hydrate with hydrate_modal.py."""
    print(
        f"""
App:       {APP_NAME}
Mode:      {SETTINGS.launch_mode}
Image:     {IMAGE_TAG}
Profile:   {PROFILE_NAME}
Workflow:  {SETTINGS.workflow_source or SETTINGS.workflow_lock_source or '(volume launch.json)'}
GPU:       {GPU}
Port:      {COMFY_PORT}
Workspace: {SETTINGS.volume_name} -> {WORKSPACE}
Storage:   {SETTINGS.models_volume_name} -> {STORAGE_ROOT}
Secret:    {SECRET_NAME}
InstallLockNodes: {INSTALL_LOCK_NODES} (Volume, not Image)
InstallExtraNodes: {INSTALL_NODES}
BaseNodes: {BASE_NODES_ENABLED}
Latest:    {FORCE_LATEST}
Snapshot:  memory={SETTINGS.memory_snapshot} gpu={SETTINGS.gpu_snapshot}

# 1. Hydrate models (CPU) — writes Volume .state/launch.json
modal run hydrate_modal.py --workflow examples/z-image-base.json
modal run hydrate_modal.py --profile qwen-image

# 2. GPU UI (same Image for every workflow; lock CNR on workspace Volume)
MODAL_GPU=T4 modal serve comfyui_modal.py
MODAL_GPU=T4 modal deploy comfyui_modal.py
""".strip()
    )
