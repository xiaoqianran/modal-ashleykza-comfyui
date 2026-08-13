"""Canonical ComfyUI paths on Modal Volumes.

One layout, no nested category folders:

    {storage_root}/{category}/{filename}     models Volume
    {workspace}/output/{filename}            workspace Volume (成片)
    {workspace}/input/{filename}
    {workspace}/models/{category}/{filename} legacy only

``filename`` is relative. Leading ``models/``, a repeated category, or a
repeated ``output/`` prefix is stripped so ``vae/vae/x.safetensors`` cannot
be written. Hydrate and GPU start also flatten any leftover nested dirs.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from recipes import MODEL_DIRS

DEFAULT_STORAGE_ROOT = Path("/mnt/comfy-storage")
DEFAULT_STORAGE_VOLUME = "comfyui-ashleykza-models"
DEFAULT_WORKSPACE = Path("/workspace")
DEFAULT_COMFY_ROOT = Path("/ComfyUI")

WORKSPACE_LEAF_DIRS = ("custom_nodes", "input", "output", "user", "logs", "state")


class PathError(ValueError):
    """Unsafe or non-canonical path."""


def posix_relative(value: str | Path, *, field: str = "path") -> PurePosixPath:
    raw = str(value).strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PathError(f"Unsafe {field}: {value!r}")
    return path


def canonical_relpath(
    value: str | Path,
    *,
    category: str | None = None,
    extra_strip: tuple[str, ...] = (),
    field: str = "path",
) -> str:
    """Relative POSIX path with redundant leading segments removed.

    ``models/vae/file.safetensors`` and ``vae/vae/file.safetensors`` with
    ``category='vae'`` both become ``file.safetensors``. Vendor subfolders
    such as ``qwen/model.safetensors`` are kept.
    """
    parts = list(posix_relative(value, field=field).parts)
    drop = {"models", *extra_strip}
    if category:
        drop.add(category)
    while len(parts) > 1 and parts[0] in drop:
        parts.pop(0)
    return PurePosixPath(*parts).as_posix()


def storage_model_path(
    storage_root: str | Path,
    category: str,
    filename: str,
) -> Path:
    if category not in MODEL_DIRS:
        raise PathError(f"Unsupported ComfyUI model category: {category!r}")
    relative = canonical_relpath(filename, category=category, field="model filename")
    return Path(storage_root) / category / relative


def legacy_model_path(
    workspace: str | Path,
    category: str,
    filename: str,
) -> Path:
    if category not in MODEL_DIRS:
        raise PathError(f"Unsupported ComfyUI model category: {category!r}")
    relative = canonical_relpath(filename, category=category, field="model filename")
    return Path(workspace) / "models" / category / relative


def workspace_dir(workspace: str | Path, name: str) -> Path:
    if name not in WORKSPACE_LEAF_DIRS:
        raise PathError(f"Unsupported workspace directory: {name!r}")
    return Path(workspace) / name


def workspace_file(workspace: str | Path, name: str, filename: str) -> Path:
    relative = canonical_relpath(
        filename,
        extra_strip=(name,),
        field=f"{name} filename",
    )
    return workspace_dir(workspace, name) / relative


def download_target(target_dir: str | Path, filename: str) -> Path:
    """Final file path for a download into ``target_dir``.

    If ``target_dir`` is a known model category folder, a leading copy of that
    category in ``filename`` is stripped (``vae/vae/x`` cannot be created).
    """
    directory = Path(target_dir)
    category = directory.name if directory.name in MODEL_DIRS else None
    relative = canonical_relpath(filename, category=category, field="download filename")
    return directory / relative


def resolve_model_file(
    *,
    storage_root: str | Path,
    workspace: str | Path,
    category: str,
    filename: str,
) -> Path:
    """Prefer the Modal models Volume, then the older workspace/models layout."""
    primary = storage_model_path(storage_root, category, filename)
    if primary.is_file() and primary.stat().st_size > 0:
        return primary
    legacy = legacy_model_path(workspace, category, filename)
    if legacy.is_file() and legacy.stat().st_size > 0:
        return legacy
    return primary


def ensure_storage_layout(storage_root: str | Path) -> Path:
    root = Path(storage_root)
    for category in MODEL_DIRS:
        (root / category).mkdir(parents=True, exist_ok=True)
    (root / ".state").mkdir(parents=True, exist_ok=True)
    return root


def ensure_workspace_layout(workspace: str | Path) -> Path:
    root = Path(workspace)
    for directory in WORKSPACE_LEAF_DIRS:
        (root / directory).mkdir(parents=True, exist_ok=True)
    for category in MODEL_DIRS:
        (root / "models" / category).mkdir(parents=True, exist_ok=True)
    return root


def extra_model_paths_yaml(
    *,
    storage_root: str | Path,
    workspace: str | Path,
) -> str:
    """Map the Modal Volume onto ComfyUI model folders without hiding Image models."""
    lines = [
        "# Generated by storage.py. Volume dirs match ComfyUI models/<category>/ names.",
        "modal_storage:",
        f"    base_path: {Path(storage_root)}",
        "    is_default: true",
    ]
    for name in MODEL_DIRS:
        lines.append(f"    {name}: {name}/")
    lines.extend(
        [
            "modal_workspace:",
            f"    base_path: {Path(workspace)}",
            "    is_default: false",
        ]
    )
    for name in MODEL_DIRS:
        lines.append(f"    {name}: models/{name}/")
    lines.append("    custom_nodes: custom_nodes/")
    lines.append("")
    return "\n".join(lines)


def _remove_empty_dirs(start: Path, stop: Path) -> None:
    current = start
    stop = stop.resolve()
    while current.exists() and current.resolve() != stop:
        try:
            parent = current.parent
            current.rmdir()
        except OSError:
            return
        current = parent


def _move_file(src: Path, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.is_file() and dest.stat().st_size > 0:
            src.unlink()
            return f"[DROP-NEST] {src} (kept {dest})"
        dest.unlink()
    src.rename(dest)
    return f"[FLATTEN] {src} -> {dest}"


def flatten_repeated_dir(parent: str | Path, name: str) -> list[str]:
    """Move ``parent/name/name/**`` onto ``parent/name/**`` until it stops nesting."""
    parent = Path(parent)
    dest_root = parent / name
    messages: list[str] = []
    while (dest_root / name).is_dir() and (dest_root / name).resolve() != dest_root.resolve():
        nested = dest_root / name
        for src in tuple(nested.rglob("*")):
            if src.is_file():
                dest = dest_root / src.relative_to(nested)
                messages.append(_move_file(src, dest))
        _remove_empty_dirs(nested, dest_root)
    return messages


def flatten_category_nests(root: str | Path, categories: Iterable[str] = MODEL_DIRS) -> list[str]:
    messages: list[str] = []
    root = Path(root)
    for category in categories:
        messages.extend(flatten_repeated_dir(root, category))
    return messages


def promote_models_prefix(root: str | Path) -> list[str]:
    """Move ``root/models/<category>/file`` onto ``root/<category>/file``."""
    root = Path(root)
    models = root / "models"
    if not models.is_dir():
        return []
    messages: list[str] = []
    for category in MODEL_DIRS:
        src_dir = models / category
        if not src_dir.is_dir():
            continue
        for src in tuple(src_dir.rglob("*")):
            if not src.is_file():
                continue
            dest = storage_model_path(root, category, str(src.relative_to(src_dir)))
            messages.append(_move_file(src, dest))
        _remove_empty_dirs(src_dir, models)
    _remove_empty_dirs(models, root)
    return messages


def repair_storage_layout(storage_root: str | Path) -> list[str]:
    """Fix leftover ``vae/vae/`` and ``models/vae/`` trees on the models Volume."""
    root = ensure_storage_layout(storage_root)
    messages = promote_models_prefix(root)
    messages.extend(flatten_category_nests(root))
    for line in messages:
        print(line, flush=True)
    return messages


def repair_workspace_layout(workspace: str | Path) -> list[str]:
    """Fix leftover ``output/output/`` and ``models/vae/vae/`` trees."""
    root = ensure_workspace_layout(workspace)
    messages: list[str] = []
    for leaf in ("output", "input", "user"):
        messages.extend(flatten_repeated_dir(root, leaf))
    messages.extend(flatten_category_nests(root / "models"))
    for line in messages:
        print(line, flush=True)
    return messages


def list_output_files(workspace: str | Path) -> list[dict[str, str | int]]:
    """Canonical listing of workspace ``output/`` after flattening nests."""
    repair_workspace_layout(workspace)
    output = workspace_dir(workspace, "output")
    files: list[dict[str, str | int]] = []
    if not output.is_dir():
        return files
    for path in sorted(output.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(output).as_posix()
        files.append(
            {
                "name": relative,
                "volume_path": f"/output/{relative}",
                "bytes": path.stat().st_size,
            }
        )
    return files
