from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# Test default is L40S, never T4. Modal treats a GPU tuple as fallback:
# L40S,RTX-PRO-6000 silently upgrades when L40S is out of capacity.
# Inference cards must stay explicit and out of this default tuple.
DEFAULT_GPU = ("L40S",)
CHEAP_GPUS = frozenset({"L40S"})
ASHLEY_REGISTRY = "ghcr.io/ashleykleynhans/comfyui"
ASHLEY_FLAVOR = "cu128-py312"
ASHLEY_DOCKER_TAGS_URL = (
    "https://api.github.com/repos/ashleykleynhans/comfyui-docker/tags?per_page=100"
)
_ASHLEY_VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
GPU_IDLE_REMINDER = (
    "任务已结束。scaledown_window=5s 只在没有 HTTP/WebSocket、也没有 modal serve "
    "保活时生效。测完请停掉 serve；浏览器开着 ComfyUI 或继续轮询 /system_stats "
    "会一直占 GPU。默认 GPU 是 L40S，RTX-PRO-6000 必须显式设置 MODAL_GPU。"
)


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
                return "1" if name.startswith(("install-", "skip-")) else ""
            return argv[index + 1].strip()
        prefix = f"{key}="
        if item.startswith(prefix):
            return item[len(prefix) :].strip()
    return ""


def parse_ashley_version(tag: str) -> tuple[int, int, int] | None:
    match = _ASHLEY_VERSION_RE.fullmatch(tag.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def latest_ashley_tag(tags: Iterable[str]) -> str:
    """Pick the highest ``vX.Y.Z`` from ashleykleynhans/comfyui-docker tags."""
    versions = [
        (version, tag.strip())
        for tag in tags
        if (version := parse_ashley_version(tag)) is not None
    ]
    if not versions:
        raise RuntimeError(
            "no ashleykleynhans/comfyui-docker vX.Y.Z tags; set COMFY_IMAGE"
        )
    _version, tag = max(versions, key=lambda item: item[0])
    return tag


def fetch_ashley_docker_tags(url: str = ASHLEY_DOCKER_TAGS_URL) -> list[str]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "modal-ashleykza-comfyui",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8") or "[]")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(
            f"cannot list ashleykleynhans/comfyui-docker tags from {url}: {exc}. "
            "set COMFY_IMAGE to pin a registry tag"
        ) from exc
    if not isinstance(payload, list):
        raise RuntimeError(
            f"unexpected ashleykleynhans/comfyui-docker tags payload: {type(payload)}"
        )
    return [str(item.get("name") or "") for item in payload if isinstance(item, dict)]


def latest_ashley_image_ref(*, tags: Iterable[str] | None = None) -> str:
    """Build-time GHCR ref: ``cu128-py312-`` + newest docker-repo ``vX.Y.Z``.

    Do not hardcode 0.32 / 0.33. Models and lock CNR stay on Volumes.
    """
    names = list(tags) if tags is not None else fetch_ashley_docker_tags()
    return f"{ASHLEY_REGISTRY}:{ASHLEY_FLAVOR}-{latest_ashley_tag(names)}"


def resolve_comfy_image(environ: Mapping[str, str]) -> str:
    """Honor ``COMFY_IMAGE`` when set; otherwise resolve the latest Ashley tag."""
    explicit = environ.get("COMFY_IMAGE", "").strip()
    if explicit:
        return explicit
    return latest_ashley_image_ref()


def parse_gpu(raw: str) -> tuple[str, ...]:
    """Parse ``MODAL_GPU``. Empty means L40S only — never a silent PRO-6000 fallback."""
    gpu = tuple(item.strip() for item in raw.split(",") if item.strip())
    return gpu or DEFAULT_GPU


def idle_release_kwargs(settings: ModalSettings) -> dict[str, int]:
    """Cls kwargs so idle GPUs go to zero. ``modal serve`` still bills until stopped."""
    return {
        "scaledown_window": settings.ui_scaledown_window_seconds,
        "min_containers": 0,
        "buffer_containers": 0,
    }


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
    install_lock_nodes: bool
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
        gpu = parse_gpu(environ.get("MODAL_GPU", ""))

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

        install_lock_nodes = _boolean(environ, "COMFY_INSTALL_LOCK_NODES", True)
        if _argv_option(argv, "skip-lock-nodes") in {"1", "true", "yes", "on"}:
            install_lock_nodes = False
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
            image_tag=environ.get("COMFY_IMAGE", "").strip(),
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
            install_lock_nodes=install_lock_nodes,
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

    def resolved_image_tag(self) -> str:
        """Explicit ``COMFY_IMAGE``, or the newest ``cu128-py312-v*`` at build time."""
        if self.image_tag:
            return self.image_tag
        return latest_ashley_image_ref()
