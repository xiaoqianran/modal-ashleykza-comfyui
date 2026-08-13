from __future__ import annotations

import sys
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


def wants_latest_dependencies(
    environ: Mapping[str, str],
    argv: Sequence[str] | None = None,
) -> bool:
    """Return whether local Modal commands should ignore Image cache for Git clones.

    ``modal serve`` always fetches the current GitHub HEAD / unpinned registry
    versions. ``modal deploy`` keeps the Image cache unless ``COMFY_LATEST=1``.
    """
    raw = environ.get("COMFY_LATEST", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    args = argv if argv is not None else sys.argv
    return any(Path(arg).name == "serve" for arg in args)


@dataclass(frozen=True)
class ModalSettings:
    app_name: str
    image_tag: str
    volume_name: str
    profile_name: str
    gpu: tuple[str, ...]
    secret_name: str
    workflow_lock_source: str
    base_nodes_enabled: bool
    latest_dependencies: bool
    ui_timeout_seconds: int
    ui_startup_timeout_seconds: int
    ui_scaledown_window_seconds: int
    ui_max_inputs: int
    ui_target_inputs: int
    ui_requires_proxy_auth: bool

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
            profile_name=environ.get("COMFY_PROFILE", "base").strip() or "base",
            gpu=gpu,
            secret_name=environ.get("MODAL_SECRET_NAME", "comfyui-creds").strip()
            or "comfyui-creds",
            workflow_lock_source=environ.get("COMFY_WORKFLOW_LOCK", "").strip(),
            base_nodes_enabled=_boolean(environ, "COMFY_BASE_NODES", True),
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
                5 * 60,
                minimum=60,
                maximum=60 * 60,
            ),
            ui_max_inputs=max_inputs,
            ui_target_inputs=target_inputs,
            ui_requires_proxy_auth=_boolean(
                environ,
                "COMFY_REQUIRE_PROXY_AUTH",
                False,
            ),
        )
