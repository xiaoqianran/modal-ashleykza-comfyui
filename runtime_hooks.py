"""Lock-id → Volume runtime hooks.

GPU start does not import catalog. New CUDA / pixi recipes register a
``RuntimeHook`` here; ``apply_volume_launch`` only walks the table.

Ensure callables are looked up on the ``comfy_engine`` module so existing
tests can keep patching ``comfy_engine.ensure_*``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from comfy_env_contract import SITE_MARK as COMFY_ENV_SITE_MARK
from sam3d_runtime import _lock_has_sam3d
from sparse_3d_runtime import (
    SPARSE_3D_SITE_MARK,
    _lock_has_pixal3d,
    _lock_has_trellis2,
    _lock_needs_sparse_3d_runtime,
)

Nodes = Sequence[Mapping[str, Any]]


@dataclass(frozen=True)
class RuntimeHook:
    name: str
    site_mark: str
    matches: Callable[[Nodes], bool]
    prepare: str | None = None
    ensure_wheels: str | None = None
    ensure_runtime: str | None = None
    wheels_kwargs: Callable[[Nodes, Path], dict[str, Any]] | None = None
    runtime_kwargs: Callable[[Nodes, Path], dict[str, Any]] | None = None


def sparse_3d_matches(nodes: Nodes) -> bool:
    return _lock_needs_sparse_3d_runtime(nodes)


def sam3d_matches(nodes: Nodes) -> bool:
    return _lock_has_sam3d(nodes)


def _sparse_wheels_kwargs(nodes: Nodes, workspace: Path) -> dict[str, Any]:
    pixal = _lock_has_pixal3d(nodes)
    return {
        "include_attention": pixal,
        "include_sparse": True,
        "include_drtk": pixal,
        "include_nvdiffrast": _lock_has_trellis2(nodes),
        "workspace": workspace,
    }


def _sparse_runtime_kwargs(nodes: Nodes, workspace: Path) -> dict[str, Any]:
    return {
        "include_pixal3d": _lock_has_pixal3d(nodes),
        "include_trellis2": _lock_has_trellis2(nodes),
        "allow_source_compile": False,
        "workspace": workspace,
    }


def _sam3d_runtime_kwargs(_nodes: Nodes, workspace: Path) -> dict[str, Any]:
    return {"workspace": workspace}


RUNTIME_HOOKS: tuple[RuntimeHook, ...] = (
    RuntimeHook(
        name="sparse-3d",
        site_mark=SPARSE_3D_SITE_MARK,
        matches=sparse_3d_matches,
        ensure_wheels="ensure_pixal3d_prebuilt_wheels",
        ensure_runtime="ensure_pixal3d_runtime",
        wheels_kwargs=_sparse_wheels_kwargs,
        runtime_kwargs=_sparse_runtime_kwargs,
    ),
    RuntimeHook(
        name="sam3d",
        site_mark=COMFY_ENV_SITE_MARK,
        matches=sam3d_matches,
        prepare="apply_comfy_env_root",
        ensure_runtime="ensure_sam3d_runtime",
        runtime_kwargs=_sam3d_runtime_kwargs,
    ),
)


def hook_named(name: str) -> RuntimeHook:
    for hook in RUNTIME_HOOKS:
        if hook.name == name:
            return hook
    raise KeyError(f"unknown runtime hook {name!r}")


def matched_hooks(nodes: Nodes) -> tuple[RuntimeHook, ...]:
    return tuple(hook for hook in RUNTIME_HOOKS if hook.matches(nodes))


def run_prepare(engine: Any, hooks: Sequence[RuntimeHook], workspace: Path) -> None:
    for hook in hooks:
        if hook.prepare:
            getattr(engine, hook.prepare)(workspace)


def run_wheels(
    engine: Any,
    hooks: Sequence[RuntimeHook],
    *,
    comfy_root: Path,
    workspace: Path,
    nodes: Nodes,
) -> bool:
    changed = False
    for hook in hooks:
        if not hook.ensure_wheels:
            continue
        kwargs = hook.wheels_kwargs(nodes, workspace) if hook.wheels_kwargs else {}
        changed = bool(getattr(engine, hook.ensure_wheels)(comfy_root, **kwargs)) or changed
    return changed


def run_runtimes(
    engine: Any,
    hooks: Sequence[RuntimeHook],
    *,
    comfy_root: Path,
    workspace: Path,
    nodes: Nodes,
) -> bool:
    changed = False
    custom_nodes_dir = workspace / "custom_nodes"
    for hook in hooks:
        if not hook.ensure_runtime:
            continue
        kwargs = hook.runtime_kwargs(nodes, workspace) if hook.runtime_kwargs else {}
        changed = (
            bool(
                getattr(engine, hook.ensure_runtime)(
                    comfy_root,
                    custom_nodes_dir,
                    **kwargs,
                )
            )
            or changed
        )
    return changed


def append_site_marks(
    newly: list[str],
    hooks: Sequence[RuntimeHook],
    *,
    changed: bool,
) -> list[str]:
    if not changed:
        return newly
    for hook in hooks:
        if hook.site_mark not in newly:
            newly.append(hook.site_mark)
    if not newly and hooks:
        newly.append(hooks[0].site_mark)
    return newly
