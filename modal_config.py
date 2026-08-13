from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


def _integer(
    environ: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}, got {value}.")
    return value


def _boolean(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value, got {raw!r}.")


def _argv_option(argv: Sequence[str] | None, name: str) -> str:
    """Read ``--name value`` or ``--name=value`` from argv. Empty if absent."""
    if not argv:
        return ""
    key = f"--{name}"
    for index, item in enumerate(argv):
        if item == key:
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                return "1" if name.startswith("install-") else ""
            return argv[index + 1].strip()
        prefix = f"{key}="
        if item.startswith(prefix):
            return item[len(prefix) :].strip()
    return ""


def wants_latest_dependencies(
    environ: Mapping[str, str],
    argv: Sequence[str] | None = None,
) -> bool:
    """Rebuild Image clone layers only when COMFY_LATEST is explicitly on.

    Models live on a persistent Modal Volume. ``hydrate`` / ``workflow-sync``
    fill that Volume on CPU; serve/deploy should not re-download them.
    """
    del argv  # kept for call-site compatibility
    return _boolean(environ, "COMFY_LATEST", False)


@dataclass(frozen=True)
class ModalSettings:
    app_name: str
    image_tag: str
    volume_name: str
    models_volume_name: str
    storage_root: str
    hydrate_workers: int
    profile_name: str
    gpu: tuple[str, ...]
    secret_name: str
    workflow_source: str
    workflow_lock_source: str
    install_nodes: bool
    base_nodes_enabled: bool
    latest_dependencies: bool
    ui_timeout_seconds: int
    ui_startup_timeout_seconds: int
    ui_scaledown_window_seconds: int
    ui_max_inputs: int
    ui_target_inputs: int
    ui_requires_proxy_auth: bool
    memory_snapshot: bool
    gpu_snapshot: bool

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str],
        argv: Sequence[str] | None = None,
    ) -> ModalSettings:
        gpu_raw = environ.get("MODAL_GPU", "").strip()
        gpu = tuple(item.strip() for item in gpu_raw.split(",") if item.strip())
        if not gpu:
            gpu = ("T4", "L4", "L40S", "RTX-PRO-6000")

        workflow_source = (
            _argv_option(argv, "workflow")
            or environ.get("COMFY_WORKFLOW", "")
        ).strip()
        profile_name = (
            _argv_option(argv, "profile")
            or environ.get("COMFY_PROFILE", "base")
        ).strip() or "base"
        workflow_lock_source = (
            _argv_option(argv, "lock-out")
            or environ.get("COMFY_WORKFLOW_LOCK", "")
        ).strip()
        if workflow_source and not workflow_lock_source:
            workflow_lock_source = str(Path(workflow_source).with_suffix(".lock.json"))

        install_nodes = _boolean(environ, "COMFY_INSTALL_NODES", False)
        if _argv_option(argv, "install-nodes") in {"1", "true", "yes", "on"}:
            install_nodes = True

        max_inputs = _integer(
            environ,
            "COMFY_MAX_INPUTS",
            20,
            minimum=1,
            maximum=100,
        )
        target_inputs = _integer(
            environ,
            "COMFY_TARGET_INPUTS",
            min(10, max_inputs),
            minimum=1,
            maximum=max_inputs,
        )

        memory_snapshot = _boolean(environ, "COMFY_MEMORY_SNAPSHOT", True)
        gpu_snapshot = _boolean(environ, "COMFY_GPU_SNAPSHOT", True) and memory_snapshot

        return cls(
            app_name=environ.get("MODAL_APP_NAME", "comfyui-ashleykza-cu128").strip()
            or "comfyui-ashleykza-cu128",
            image_tag=environ.get(
                "COMFY_IMAGE",
                "ghcr.io/ashleykleynhans/comfyui:cu128-py312-v0.32.0",
            ).strip(),
            volume_name=environ.get(
                "MODAL_VOLUME_NAME",
                "comfyui-ashleykza-workspace",
            ).strip()
            or "comfyui-ashleykza-workspace",
            models_volume_name=environ.get(
                "MODAL_MODELS_VOLUME",
                "comfyui-ashleykza-models",
            ).strip()
            or "comfyui-ashleykza-models",
            storage_root=environ.get("COMFY_STORAGE_ROOT", "/mnt/comfy-storage").strip()
            or "/mnt/comfy-storage",
            hydrate_workers=_integer(
                environ,
                "COMFY_HYDRATE_WORKERS",
                4,
                minimum=1,
                maximum=16,
            ),
            profile_name=profile_name,
            gpu=gpu,
            secret_name=environ.get("MODAL_SECRET_NAME", "comfyui-creds").strip()
            or "comfyui-creds",
            workflow_source=workflow_source,
            workflow_lock_source=workflow_lock_source,
            install_nodes=install_nodes,
            base_nodes_enabled=_boolean(environ, "COMFY_BASE_NODES", False),
            latest_dependencies=wants_latest_dependencies(environ, argv),
            ui_timeout_seconds=_integer(
                environ,
                "COMFY_TIMEOUT_SECONDS",
                24 * 60 * 60,
                minimum=60,
                maximum=24 * 60 * 60,
            ),
            ui_startup_timeout_seconds=_integer(
                environ,
                "COMFY_STARTUP_TIMEOUT_SECONDS",
                15 * 60,
                minimum=30,
                maximum=60 * 60,
            ),
            ui_scaledown_window_seconds=_integer(
                environ,
                "COMFY_SCALEDOWN_SECONDS",
                5,
                minimum=2,
                maximum=20 * 60,
            ),
            ui_max_inputs=max_inputs,
            ui_target_inputs=target_inputs,
            ui_requires_proxy_auth=_boolean(
                environ,
                "COMFY_REQUIRE_PROXY_AUTH",
                False,
            ),
            memory_snapshot=memory_snapshot,
            gpu_snapshot=gpu_snapshot,
        )

    @property
    def launch_mode(self) -> str:
        """``workflow`` if a JSON/PNG was given, otherwise ``profile``."""
        return "workflow" if self.workflow_source else "profile"
