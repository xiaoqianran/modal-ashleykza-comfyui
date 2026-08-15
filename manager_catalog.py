"""ComfyUI-Manager catalogs: the plugin's JSON → missing nodes / models.

This is the same data Manager uses when you load a workflow and click
"Install Missing Custom Nodes" / Model Manager "In Workflow". It does not
invent HuggingFace repos. Hits only, otherwise leave ``unresolved``.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from recipes import MODEL_DIRS
from storage import PathError, canonical_relpath
from workflow_resolver import (
    CNR_ID_RE,
    CORE_NODE_IDS,
    MODEL_EXTENSIONS,
    WorkflowResolutionError,
    _canonical_download_url,
    _nodes,
    dump_workflow_lock,
    load_workflow,
    load_workflow_lock,
    lock_matches_workflow,
    resolve_workflow,
    validate_workflow_lock,
)

EXTENSION_MAP_URL = (
    "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/"
    "extension-node-map.json"
)
MODEL_LIST_URL = (
    "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/model-list.json"
)
CUSTOM_NODE_LIST_URL = (
    "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/"
    "custom-node-list.json"
)
CACHE_DIR = Path(".cache/comfyui-manager")
GITHUB_REPO_RE = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)

# Manager ``type`` → ComfyUI folder. Unknown types stay unresolved.
TYPE_TO_DIR = {
    "audio": "audio_encoders",
    "audioencoder": "audio_encoders",
    "checkpoint": "checkpoints",
    "checkpoints": "checkpoints",
    "clip": "clip",
    "clip_vision": "clip_vision",
    "clipvision": "clip_vision",
    "controlnet": "controlnet",
    "diffusion": "diffusion_models",
    "diffusion_model": "diffusion_models",
    "diffusion_models": "diffusion_models",
    "embedding": "embeddings",
    "embeddings": "embeddings",
    "gligen": "gligen",
    "hypernetwork": "hypernetworks",
    "hypernetworks": "hypernetworks",
    "lora": "loras",
    "loras": "loras",
    "photomaker": "photomaker",
    "style": "style_models",
    "style_models": "style_models",
    "taesd": "vae_approx",
    "text_encoder": "text_encoders",
    "text_encoders": "text_encoders",
    "unet": "unet",
    "upscale": "upscale_models",
    "upscale_models": "upscale_models",
    "upscaler": "upscale_models",
    "vae": "vae",
    "vae_approx": "vae_approx",
}


def _http_json(url: str, timeout: int = 60) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "modal-ashleykza-comfyui-manager-catalog"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _read_cache(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_json(url: str, cache_path: Path, *, refresh: bool = False) -> Any:
    if not refresh:
        cached = _read_cache(cache_path)
        if cached is not None:
            return cached
    payload = _http_json(url)
    _write_cache(cache_path, payload)
    return payload


def github_repo_id(url: str) -> str | None:
    match = GITHUB_REPO_RE.match(url.strip())
    if not match:
        return None
    name = match.group(2)
    if name.lower() in CORE_NODE_IDS:
        return None
    return name


def category_from_manager_entry(entry: Mapping[str, Any]) -> str | None:
    save = str(entry.get("save_path") or "default").strip().replace("\\", "/")
    if save.startswith("models/"):
        save = save[len("models/") :]
    if save and save != "default":
        first = PurePosixPath(save).parts[0] if save else ""
        if first in MODEL_DIRS:
            return first
        return None
    type_name = re.sub(r"[^a-z0-9]+", "", str(entry.get("type") or "").lower())
    return TYPE_TO_DIR.get(str(entry.get("type") or "").strip().lower()) or TYPE_TO_DIR.get(
        type_name
    )


def index_extension_map(payload: Mapping[str, Any]) -> dict[str, list[str]]:
    """class_type → unique GitHub repo URLs (Manager extension-node-map)."""
    by_type: dict[str, list[str]] = {}
    for raw_url, body in payload.items():
        repo = github_repo_id(str(raw_url))
        match = GITHUB_REPO_RE.match(str(raw_url).strip())
        if repo is None or match is None:
            continue
        url = f"https://github.com/{match.group(1)}/{repo}"
        names: Iterable[Any] = ()
        if isinstance(body, list) and body and isinstance(body[0], list):
            names = body[0]
        elif isinstance(body, list):
            names = [item for item in body if isinstance(item, str)]
        for name in names:
            if not isinstance(name, str) or not name.strip():
                continue
            bucket = by_type.setdefault(name, [])
            if url not in bucket:
                bucket.append(url)
    return by_type


def index_model_list(payload: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    rows = payload.get("models") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        filename = str(item.get("filename") or "").strip().replace("\\", "/")
        url = str(item.get("url") or "").strip()
        if not filename or not url:
            continue
        suffix = PurePosixPath(filename).suffix.lower()
        if suffix and suffix not in MODEL_EXTENSIONS:
            continue
        try:
            url = _canonical_download_url(url)
        except Exception:
            continue
        by_name.setdefault(PurePosixPath(filename).name, []).append(
            {
                "filename": filename,
                "url": url,
                "category": category_from_manager_entry(item),
                "save_path": item.get("save_path"),
                "type": item.get("type"),
                "name": item.get("name"),
            }
        )
    return by_name


def index_custom_node_list(payload: Mapping[str, Any]) -> dict[str, str]:
    """github repo URL → CNR / Manager id when the list has one."""
    rows = payload.get("custom_nodes") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return {}
    mapped: dict[str, str] = {}
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        node_id = item.get("id") or item.get("name")
        files = item.get("files") or item.get("reference")
        urls: list[str] = []
        if isinstance(files, list):
            urls.extend(str(value) for value in files)
        elif isinstance(files, str):
            urls.append(files)
        if isinstance(item.get("reference"), str):
            urls.append(str(item["reference"]))
        if not isinstance(node_id, str) or not node_id.strip():
            continue
        for url in urls:
            repo = github_repo_id(url)
            match = GITHUB_REPO_RE.match(url.strip())
            if repo is None or match is None:
                continue
            key = f"https://github.com/{match.group(1)}/{repo}"
            mapped.setdefault(key.lower(), node_id.strip())
    return mapped


class ManagerCatalog:
    def __init__(
        self,
        *,
        extension_map: Mapping[str, Any] | None = None,
        model_list: Mapping[str, Any] | None = None,
        custom_node_list: Mapping[str, Any] | None = None,
    ) -> None:
        self.nodes_by_type = index_extension_map(extension_map or {})
        self.models_by_name = index_model_list(model_list or {})
        self.id_by_repo = index_custom_node_list(custom_node_list or {})

    @classmethod
    def load(
        cls,
        cache_dir: str | Path = CACHE_DIR,
        *,
        refresh: bool = False,
    ) -> ManagerCatalog:
        cache = Path(cache_dir)
        return cls(
            extension_map=fetch_json(
                EXTENSION_MAP_URL, cache / "extension-node-map.json", refresh=refresh
            ),
            model_list=fetch_json(MODEL_LIST_URL, cache / "model-list.json", refresh=refresh),
            custom_node_list=fetch_json(
                CUSTOM_NODE_LIST_URL, cache / "custom-node-list.json", refresh=refresh
            ),
        )


def _pick_model_entry(filename: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    basename = PurePosixPath(filename).name
    exact = [item for item in entries if PurePosixPath(item["filename"]).name == basename]
    pool = exact or entries
    urls = {item["url"] for item in pool}
    if len(urls) != 1:
        return None
    with_category = [item for item in pool if item.get("category") in MODEL_DIRS]
    if len({item["category"] for item in with_category}) > 1:
        return None
    return with_category[0] if with_category else pool[0]


def bind_manager_models(
    unresolved: Iterable[Mapping[str, Any]],
    catalog: ManagerCatalog,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    bound: list[dict[str, Any]] = []
    leftover: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for item in unresolved:
        filename = str(item.get("filename") or "")
        basename = PurePosixPath(filename).name
        entries = catalog.models_by_name.get(basename) or []
        picked = _pick_model_entry(filename, entries) if entries else None
        if picked is None:
            if len(entries) > 1:
                warnings.append(
                    {
                        "code": "manager_model_conflict",
                        "filename": filename,
                        "urls": sorted({row["url"] for row in entries}),
                    }
                )
            leftover.append(dict(item))
            continue
        category = item.get("category") if item.get("category") in MODEL_DIRS else picked.get("category")
        if category not in MODEL_DIRS:
            leftover.append({**dict(item), "url": picked["url"], "reason": "missing_category"})
            warnings.append(
                {
                    "code": "missing_category",
                    "filename": filename,
                    "url": picked["url"],
                    "detail": "ComfyUI-Manager has a URL but no known models/ folder",
                }
            )
            continue
        try:
            stored = canonical_relpath(filename, category=str(category), field="model name")
        except PathError:
            leftover.append(dict(item))
            continue
        bound.append(
            {
                "category": category,
                "filename": stored,
                "url": picked["url"],
                "sha256": None,
                "source": "comfyui-manager",
            }
        )
    return bound, leftover, warnings


def bind_manager_nodes(
    workflow_nodes: Iterable[Mapping[str, Any]],
    existing: Iterable[Mapping[str, Any]],
    catalog: ManagerCatalog,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    have = {str(node.get("id") or "").lower() for node in existing}
    have_types = {
        name
        for node in existing
        for name in (node.get("node_types") or ())
        if isinstance(name, str)
    }
    added: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, Any]] = []
    for node in workflow_nodes:
        properties = node.get("properties")
        cnr_id = properties.get("cnr_id") if isinstance(properties, Mapping) else None
        if isinstance(cnr_id, str) and cnr_id.strip().lower() in CORE_NODE_IDS:
            continue
        node_type = str(node.get("type") or node.get("class_type") or "")
        if not node_type or node_type in have_types:
            continue
        repos = catalog.nodes_by_type.get(node_type) or []
        if not repos:
            continue
        if len(repos) != 1:
            warnings.append(
                {
                    "code": "manager_node_conflict",
                    "node_type": node_type,
                    "urls": repos,
                }
            )
            continue
        url = repos[0]
        repo_id = github_repo_id(url)
        if repo_id is None:
            continue
        listed = catalog.id_by_repo.get(url.lower()) or repo_id
        node_id = listed if CNR_ID_RE.fullmatch(listed) else repo_id
        key = node_id.lower()
        if key in have or key in CORE_NODE_IDS:
            continue
        bucket = added.setdefault(
            key,
            {"id": node_id, "version": None, "url": url, "node_types": set(), "source": "comfyui-manager"},
        )
        bucket["node_types"].add(node_type)
    resolved = []
    for item in added.values():
        resolved.append(
            {
                "id": item["id"],
                "version": item["version"],
                "url": item["url"],
                "node_types": sorted(item["node_types"]),
                "source": "comfyui-manager",
            }
        )
    return resolved, warnings


def enrich_lock(
    lock: Mapping[str, Any],
    workflow: Mapping[str, Any],
    catalog: ManagerCatalog,
) -> dict[str, Any]:
    payload = dict(lock)
    nodes = _nodes(workflow)
    extra_nodes, node_warnings = bind_manager_nodes(nodes, payload.get("custom_nodes") or (), catalog)
    if extra_nodes:
        merged = {str(node.get("id")).lower(): dict(node) for node in payload.get("custom_nodes") or ()}
        for node in extra_nodes:
            merged.setdefault(str(node["id"]).lower(), node)
        payload["custom_nodes"] = [merged[key] for key in sorted(merged)]
    extra_models, leftover, model_warnings = bind_manager_models(
        payload.get("unresolved") or (),
        catalog,
    )
    if extra_models:
        merged_models = {
            (model["category"], model["filename"]): dict(model)
            for model in payload.get("models") or ()
        }
        for model in extra_models:
            merged_models[(model["category"], model["filename"])] = model
        payload["models"] = [merged_models[key] for key in sorted(merged_models)]
    payload["unresolved"] = leftover
    payload["warnings"] = [
        *(payload.get("warnings") or []),
        *node_warnings,
        *model_warnings,
    ]
    payload["manager"] = {
        "models_bound": len(extra_models),
        "nodes_bound": len(extra_nodes),
        "unresolved": len(leftover),
    }
    validate_workflow_lock(payload, require_resolved=False)
    return payload


def resolve_with_manager(
    workflow_path: str | Path,
    catalog: ManagerCatalog | None = None,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    lock = resolve_workflow(workflow_path)
    workflow, _raw = load_workflow(workflow_path)
    loaded = catalog or ManagerCatalog.load(refresh=refresh)
    return enrich_lock(lock, workflow, loaded)


def _existing_lock(lock_path: Path) -> dict[str, Any] | None:
    if not lock_path.is_file():
        return None
    try:
        return load_workflow_lock(lock_path, require_resolved=False)
    except (WorkflowResolutionError, OSError, json.JSONDecodeError):
        return None


def _is_curated(lock: Mapping[str, Any] | None) -> bool:
    return bool(lock and not lock.get("unresolved") and lock.get("models"))


def classify_probe_nodes(
    missing_nodes: Iterable[str],
    custom_nodes: Iterable[Mapping[str, Any]],
) -> dict[str, list[str]]:
    """Split CPU-missing types into already-locked vs still unknown."""
    mapped = {
        name
        for node in custom_nodes
        for name in (node.get("node_types") or ())
        if isinstance(name, str)
    }
    missing = [name for name in missing_nodes]
    return {
        "missing_nodes_in_lock": [name for name in missing if name in mapped],
        "missing_nodes_unmapped": [name for name in missing if name not in mapped],
    }


def prepare_probe_lock(
    workflow_path: str | Path,
    lock_path: str | Path,
    catalog: ManagerCatalog | None = None,
    *,
    refresh: bool = False,
) -> tuple[dict[str, Any], str]:
    """Fill a lock from Manager catalogs without clobbering a curated file.

    Origin is ``curated`` when the on-disk lock is fully resolved and still
    matches the workflow sha256. Otherwise write a Manager-enriched lock even
    if some models stay ``unresolved``.
    """
    workflow_path = Path(workflow_path)
    lock_path = Path(lock_path)
    existing = _existing_lock(lock_path)
    if _is_curated(existing) and lock_matches_workflow(existing, workflow_path):
        return dict(existing), "curated"
    filled = resolve_with_manager(workflow_path, catalog, refresh=refresh)
    if _is_curated(existing) and filled.get("unresolved"):
        raise WorkflowResolutionError(
            f"{workflow_path} changed but ComfyUI-Manager still left unresolved "
            f"models. Will not overwrite curated {lock_path}."
        )
    dump_workflow_lock(filled, lock_path)
    return filled, "manager"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Fill a workflow lock from ComfyUI-Manager catalogs (no GPU).",
    )
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--lock-out", default="")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--cache-dir", default=str(CACHE_DIR))
    args = parser.parse_args(argv)
    catalog = ManagerCatalog.load(args.cache_dir, refresh=args.refresh)
    lock = resolve_with_manager(args.workflow, catalog)
    if args.lock_out:
        dump_workflow_lock(lock, args.lock_out)
    print(json.dumps(
        {
            "models": len(lock["models"]),
            "custom_nodes": lock["custom_nodes"],
            "unresolved": lock["unresolved"],
            "manager": lock.get("manager"),
            "warnings": lock.get("warnings"),
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
