"""Single allowlist for Modal Image mounts and Windows Studio.exe.

Add a new runtime module here once. GPU Image, hydrate Image, packaging,
and the completeness test all read this tuple.
"""

from __future__ import annotations

# ``modal.Image.add_local_python_source`` names (no .py suffix).
GPU_PYTHON_SOURCES: tuple[str, ...] = (
    "base_nodes",
    "recipes",
    "workflow_resolver",
    "comfy_engine",
    "comfy_env_contract",
    "runtime_hooks",
    "sparse_3d_runtime",
    "uv_runtime",
    "sam3d_runtime",
    "modal_config",
    "shipped_modules",
    "storage",
    "asset_sync",
    "engine_util",
    "node_install",
)

# Hydrate is CPU-only and never runs the 130-node Image installer.
HYDRATE_PYTHON_SOURCES: tuple[str, ...] = tuple(
    name for name in GPU_PYTHON_SOURCES if name != "base_nodes"
)

# Extra top-level modules the Windows exe needs that are not GPU Image sources.
WINDOWS_EXTRA_MODULES: tuple[str, ...] = (
    "comfyui_modal.py",
    "hydrate_modal.py",
    "workflow_queue.py",
)


def _py_name(module: str) -> str:
    return module if module.endswith(".py") else f"{module}.py"


def windows_modules() -> tuple[str, ...]:
    seen: list[str] = []
    for name in (*(_py_name(item) for item in GPU_PYTHON_SOURCES), *WINDOWS_EXTRA_MODULES):
        if name not in seen:
            seen.append(name)
    return tuple(seen)
