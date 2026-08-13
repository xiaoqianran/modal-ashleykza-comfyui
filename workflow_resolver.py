from __future__ import annotations

import hashlib
import json
import re
import struct
import zlib
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

from recipes import MODEL_DIRS
from storage import PathError, canonical_relpath

WORKFLOW_LOCK_SCHEMA = 1
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MODEL_EXTENSIONS = {
    ".bin",
    ".ckpt",
    ".engine",
    ".gguf",
    ".onnx",
    ".pt",
    ".pth",
    ".safetensors",
}
CORE_NODE_IDS = {"comfy-core", "comfyui", "comfyui-core"}
NOTE_NODE_TYPES = {"markdownnote", "note"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
CNR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SEMVER_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9.]+)?$")
DOWNLOAD_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:huggingface\.co|hf\.co|civitai\.com)/[^\s\]\)<>\"'\\]+",
    re.IGNORECASE,
)
HF_HOSTS = {"huggingface.co", "hf.co", "www.huggingface.co"}
DOWNLOAD_HOSTS = HF_HOSTS | {"civitai.com", "www.civitai.com"}
DROP_QUERY_KEYS = {"download"}

NODE_CATEGORY_HINTS = {
    "checkpoint": "checkpoints",
    "clipvision": "clip_vision",
    "controlnet": "controlnet",
    "diffusion": "diffusion_models",
    "gguf": "diffusion_models",
    "lora": "loras",
    "textencoder": "text_encoders",
    "unet": "diffusion_models",
    "upscale": "upscale_models",
    "vae": "vae",
    "audioencoder": "audio_encoders",
    "whisper": "audio_encoders",
}


class WorkflowResolutionError(ValueError):
    """Raised when a workflow or its declared dependency metadata is unsafe."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compact_node_type(node_type: str) -> str:
    return re.sub(r"[^a-z0-9]", "", node_type.lower())


def _is_note_node(node_type: str) -> bool:
    return _compact_node_type(node_type) in NOTE_NODE_TYPES


def _is_semver(value: str) -> bool:
    return bool(SEMVER_RE.fullmatch(value))


def _canonical_download_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "hf.co":
        host = "huggingface.co"
    path = parsed.path
    if host in HF_HOSTS or host == "huggingface.co":
        path = path.replace("/blob/", "/resolve/", 1)
        if path.endswith("/") and PurePosixPath(path.rstrip("/")).suffix.lower() in MODEL_EXTENSIONS:
            path = path.rstrip("/")
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in DROP_QUERY_KEYS
        ]
    )
    return urlunparse((parsed.scheme.lower(), host, path, "", query, ""))


def _url_basename(url: str) -> str:
    return unquote(PurePosixPath(urlparse(url).path).name)


def _category_from_url(url: str) -> str | None:
    parts = PurePosixPath(urlparse(url).path).parts
    found: str | None = None
    for part in parts[:-1]:
        if part in MODEL_DIRS:
            found = part
    return found


def _prefer_cnr_version(seen: list[str | None]) -> str | None:
    nonempty = [value for value in seen if value]
    if not nonempty:
        return None
    counts = Counter(nonempty)
    pool = [value for value in counts if _is_semver(value)] or list(counts)
    return max(pool, key=lambda value: (counts[value], -seen.index(value)))


def _warning(code: str, **fields: Any) -> dict[str, Any]:
    return {"code": code, **fields}


def _json_object(value: str | bytes, *, source: str) -> dict[str, Any]:
    try:
        data = json.loads(value)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WorkflowResolutionError(f"Invalid workflow JSON in {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowResolutionError(f"Workflow root in {source} must be a JSON object.")
    return data


def _decode_png_text(kind: bytes, payload: bytes) -> tuple[str, str] | None:
    try:
        if kind == b"tEXt":
            keyword, value = payload.split(b"\0", 1)
            return keyword.decode("latin-1"), value.decode("latin-1")

        if kind == b"zTXt":
            keyword, rest = payload.split(b"\0", 1)
            method, compressed = rest[0], rest[1:]
            if method != 0:
                return None
            return keyword.decode("latin-1"), zlib.decompress(compressed).decode("utf-8")

        if kind == b"iTXt":
            keyword, rest = payload.split(b"\0", 1)
            if len(rest) < 2:
                return None
            compressed, method, rest = rest[0], rest[1], rest[2:]
            _language, rest = rest.split(b"\0", 1)
            _translated, value = rest.split(b"\0", 1)
            if compressed:
                if method != 0:
                    return None
                value = zlib.decompress(value)
            return keyword.decode("latin-1"), value.decode("utf-8")
    except (IndexError, UnicodeDecodeError, ValueError, zlib.error):
        return None
    return None


def _png_metadata(data: bytes) -> dict[str, str]:
    if not data.startswith(PNG_SIGNATURE):
        raise WorkflowResolutionError("The supplied .png file has an invalid PNG signature.")

    metadata: dict[str, str] = {}
    cursor = len(PNG_SIGNATURE)
    while cursor + 12 <= len(data):
        length = struct.unpack(">I", data[cursor : cursor + 4])[0]
        kind = data[cursor + 4 : cursor + 8]
        payload_start = cursor + 8
        payload_end = payload_start + length
        chunk_end = payload_end + 4
        if chunk_end > len(data):
            raise WorkflowResolutionError("The supplied PNG contains a truncated chunk.")

        decoded = _decode_png_text(kind, data[payload_start:payload_end])
        if decoded:
            key, value = decoded
            metadata[key] = value
        cursor = chunk_end
        if kind == b"IEND":
            break
    return metadata


def load_workflow(path: str | Path) -> tuple[dict[str, Any], bytes]:
    workflow_path = Path(path)
    raw = workflow_path.read_bytes()
    suffix = workflow_path.suffix.lower()

    if suffix == ".json":
        return _json_object(raw, source=str(workflow_path)), raw

    if suffix == ".png":
        metadata = _png_metadata(raw)
        for key in ("workflow", "Workflow", "prompt"):
            if key in metadata:
                return _json_object(metadata[key], source=f"{workflow_path}:{key}"), raw
        raise WorkflowResolutionError(
            f"PNG {workflow_path} does not contain ComfyUI workflow or prompt metadata."
        )

    raise WorkflowResolutionError("Only ComfyUI .json and workflow-embedded .png files are supported.")


def _iter_values(value: Any) -> Iterator[Any]:
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _iter_values(child)
    elif isinstance(value, list | tuple):
        for child in value:
            yield from _iter_values(child)
    else:
        yield value


def _iter_node_lists(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, Mapping):
        nodes = value.get("nodes")
        if isinstance(nodes, list):
            for node in nodes:
                if isinstance(node, dict):
                    yield node
        for child in value.values():
            yield from _iter_node_lists(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_node_lists(child)


def _iter_api_nodes(workflow: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node:
            continue
        yield {
            "id": node_id,
            "type": node.get("class_type", ""),
            "widgets_values": node.get("inputs", {}),
            "properties": node.get("properties", {}),
        }


def _nodes(workflow: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes = list(_iter_node_lists(workflow))
    nodes.extend(_iter_api_nodes(workflow))
    return nodes


def _safe_relative(value: str, *, field: str) -> PurePosixPath:
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise WorkflowResolutionError(f"Unsafe {field}: {value!r}")
    return path


def _model_destination(directory: str, name: str) -> tuple[str, str]:
    directory_path = _safe_relative(directory, field="model directory")
    parts = list(directory_path.parts)
    if parts and parts[0] == "models":
        parts.pop(0)
    if not parts or parts[0] not in MODEL_DIRS:
        raise WorkflowResolutionError(
            f"Unsupported model directory {directory!r}; expected models/<known-category>."
        )

    category = parts.pop(0)
    name_path = _safe_relative(name, field="model name")
    joined = PurePosixPath(*parts, *name_path.parts)
    try:
        filename = canonical_relpath(
            joined.as_posix(),
            category=category,
            field="model name",
        )
    except PathError as exc:
        raise WorkflowResolutionError(str(exc)) from exc
    return category, filename


def _model_url(value: Any) -> str:
    if not isinstance(value, str):
        raise WorkflowResolutionError("Model metadata is missing a download URL.")
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WorkflowResolutionError(f"Unsupported model URL: {value!r}")
    return _canonical_download_url(value)


def _model_sha256(model: Mapping[str, Any]) -> str | None:
    value = model.get("sha256") or model.get("hash")
    if not value:
        return None
    hash_type = str(model.get("hash_type", "SHA256")).replace("-", "").lower()
    if hash_type != "sha256" or not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise WorkflowResolutionError("Only a valid SHA256 model hash is supported.")
    return value.lower()


def _declared_models(
    workflow: Mapping[str, Any],
    nodes: Iterable[Mapping[str, Any]],
) -> tuple[list[dict], list[dict[str, Any]]]:
    declarations: list[tuple[str, Any]] = []
    if isinstance(workflow.get("models"), list):
        declarations.extend(("workflow.models", item) for item in workflow["models"])

    for node in nodes:
        properties = node.get("properties")
        if not isinstance(properties, Mapping) or not isinstance(properties.get("models"), list):
            continue
        node_type = str(node.get("type") or node.get("class_type") or "unknown")
        declarations.extend((f"node:{node_type}", item) for item in properties["models"])

    resolved: dict[tuple[str, str], dict] = {}
    conflicted: set[tuple[str, str]] = set()
    warnings: list[dict[str, Any]] = []
    for source, declaration in declarations:
        if not isinstance(declaration, Mapping):
            warnings.append(_warning("malformed_model", source=source, detail="not an object"))
            continue
        name = declaration.get("name") or declaration.get("filename")
        directory = declaration.get("directory") or declaration.get("folder")
        if not isinstance(name, str) or not isinstance(directory, str):
            warnings.append(
                _warning(
                    "malformed_model",
                    source=source,
                    detail="missing string name and directory",
                )
            )
            continue
        try:
            category, filename = _model_destination(directory, name)
            url = _model_url(declaration.get("url"))
            sha256 = _model_sha256(declaration)
        except WorkflowResolutionError as exc:
            message = str(exc)
            if message.startswith("Unsafe"):
                raise
            code = (
                "unsupported_directory"
                if "Unsupported model directory" in message
                else "invalid_model_declaration"
            )
            warnings.append(
                _warning(code, source=source, directory=directory, name=name, detail=message)
            )
            continue

        key = (category, filename)
        if key in conflicted:
            continue
        entry = {
            "category": category,
            "filename": filename,
            "url": url,
            "sha256": sha256,
            "source": source,
        }
        previous = resolved.get(key)
        if previous is None:
            resolved[key] = entry
            continue
        if previous["url"] == entry["url"]:
            if previous["sha256"] and entry["sha256"] and previous["sha256"] != entry["sha256"]:
                warnings.append(
                    _warning(
                        "hash_conflict",
                        category=category,
                        filename=filename,
                        detail="same URL with two SHA256 values",
                    )
                )
                del resolved[key]
                conflicted.add(key)
                continue
            if not previous["sha256"] and entry["sha256"]:
                previous["sha256"] = entry["sha256"]
            continue
        if previous["sha256"] and entry["sha256"] and previous["sha256"] == entry["sha256"]:
            continue
        warnings.append(
            _warning(
                "url_conflict",
                category=category,
                filename=filename,
                urls=sorted({previous["url"], entry["url"]}),
            )
        )
        del resolved[key]
        conflicted.add(key)
    return [resolved[key] for key in sorted(resolved)], warnings


def _custom_nodes(
    nodes: Iterable[Mapping[str, Any]],
) -> tuple[list[dict], list[dict[str, Any]]]:
    buckets: dict[str, dict[str, Any]] = {}
    for node in nodes:
        properties = node.get("properties")
        if not isinstance(properties, Mapping):
            continue
        cnr_id = properties.get("cnr_id")
        if not isinstance(cnr_id, str) or cnr_id.strip().lower() in CORE_NODE_IDS:
            continue

        node_id = cnr_id.strip().lower()
        version = properties.get("ver")
        version = str(version).strip() if version is not None else None
        node_type = str(node.get("type") or node.get("class_type") or "unknown")
        bucket = buckets.setdefault(node_id, {"versions": [], "node_types": set()})
        bucket["versions"].append(version)
        bucket["node_types"].add(node_type)

    resolved: dict[str, dict] = {}
    warnings: list[dict[str, Any]] = []
    for node_id, bucket in buckets.items():
        seen: list[str | None] = bucket["versions"]
        nonempty_unique = {value for value in seen if value}
        kept = _prefer_cnr_version(seen)
        if len(nonempty_unique) > 1:
            dropped = sorted(value for value in nonempty_unique if value != kept)
            warnings.append(
                _warning(
                    "version_conflict",
                    id=node_id,
                    kept=kept,
                    dropped=dropped,
                )
            )
        resolved[node_id] = {
            "id": node_id,
            "version": kept,
            "node_types": sorted(bucket["node_types"]),
        }
    return [resolved[key] for key in sorted(resolved)], warnings


def _category_hint(node_type: str) -> str | None:
    compact = _compact_node_type(node_type)
    for token, category in NODE_CATEGORY_HINTS.items():
        if token in compact:
            return category
    return None


def _referenced_models(
    nodes: Iterable[Mapping[str, Any]],
) -> tuple[list[dict], list[dict[str, Any]]]:
    references: dict[tuple[str | None, str], dict] = {}
    warnings: list[dict[str, Any]] = []
    for node in nodes:
        node_type = str(node.get("type") or node.get("class_type") or "unknown")
        if _is_note_node(node_type):
            continue
        category = _category_hint(node_type)
        for value in _iter_values(node.get("widgets_values", ())):
            if not isinstance(value, str) or urlparse(value).scheme:
                continue
            candidate = value.strip().replace("\\", "/")
            if PurePosixPath(candidate).suffix.lower() not in MODEL_EXTENSIONS:
                continue
            try:
                filename = _safe_relative(candidate, field="referenced model name").as_posix()
            except WorkflowResolutionError as exc:
                warnings.append(
                    _warning(
                        "unsafe_reference",
                        node_type=node_type,
                        value=candidate,
                        detail=str(exc),
                    )
                )
                continue
            parts = list(PurePosixPath(filename).parts)
            widget_category = category
            if parts and parts[0] == "models":
                parts = parts[1:]
            if widget_category is None and parts and parts[0] in MODEL_DIRS:
                widget_category = parts[0]
                parts = parts[1:]
            elif widget_category and parts and parts[0] == widget_category:
                parts = parts[1:]
            if parts:
                filename = PurePosixPath(*parts).as_posix()
            key = (widget_category, filename)
            references[key] = {
                "kind": "model",
                "category": widget_category,
                "filename": filename,
                "node_type": node_type,
                "reason": "missing_download_metadata",
            }
    return [
        references[key] for key in sorted(references, key=lambda item: (item[0] or "", item[1]))
    ], warnings


def _note_urls_by_basename(
    nodes: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    collected: dict[str, dict[str, str]] = {}
    for node in nodes:
        node_type = str(node.get("type") or node.get("class_type") or "unknown")
        if not _is_note_node(node_type):
            continue
        for value in _iter_values(node.get("widgets_values", ())):
            if not isinstance(value, str):
                continue
            for raw in DOWNLOAD_URL_RE.findall(value):
                raw = raw.rstrip(".,;:)")
                parsed = urlparse(raw)
                host = parsed.netloc.lower()
                if host.startswith("www."):
                    host = host[4:]
                if parsed.scheme not in {"http", "https"} or host not in DOWNLOAD_HOSTS:
                    continue
                basename = _url_basename(raw)
                if PurePosixPath(basename).suffix.lower() not in MODEL_EXTENSIONS:
                    continue
                canonical = _canonical_download_url(raw)
                collected.setdefault(basename, {})[canonical] = canonical
    unique: dict[str, str] = {}
    warnings: list[dict[str, Any]] = []
    for basename, urls in collected.items():
        if len(urls) == 1:
            unique[basename] = next(iter(urls))
            continue
        warnings.append(
            _warning("note_url_conflict", filename=basename, urls=sorted(urls))
        )
    return unique, warnings


def _bind_note_models(
    references: Iterable[Mapping[str, Any]],
    declared: Iterable[Mapping[str, Any]],
    note_urls: Mapping[str, str],
) -> tuple[list[dict], list[dict], list[dict[str, Any]]]:
    declared_keys = {(model["category"], model["filename"]) for model in declared}
    declared_basenames = {PurePosixPath(model["filename"]).name for model in declared}
    extra: dict[tuple[str, str], dict] = {}
    unresolved: list[dict] = []
    warnings: list[dict[str, Any]] = []
    for reference in references:
        filename = str(reference["filename"])
        basename = PurePosixPath(filename).name
        key = (reference.get("category"), filename)
        if key in declared_keys or basename in declared_basenames:
            continue
        url = note_urls.get(basename)
        if not url:
            unresolved.append(dict(reference))
            continue
        category = reference.get("category") or _category_from_url(url)
        if category not in MODEL_DIRS:
            item = dict(reference)
            item["reason"] = "missing_category"
            item["url"] = url
            unresolved.append(item)
            warnings.append(
                _warning(
                    "missing_category",
                    filename=filename,
                    url=url,
                    detail="note URL matched the basename but no known ComfyUI folder",
                )
            )
            continue
        try:
            stored = canonical_relpath(filename, category=str(category), field="model name")
        except PathError as exc:
            item = dict(reference)
            item["reason"] = "unsafe_path"
            unresolved.append(item)
            warnings.append(_warning("unsafe_reference", filename=filename, detail=str(exc)))
            continue
        extra[(category, stored)] = {
            "category": category,
            "filename": stored,
            "url": url,
            "sha256": None,
            "source": "note",
        }
    return [extra[key] for key in sorted(extra)], unresolved, warnings


def resolve_workflow(path: str | Path) -> dict[str, Any]:
    workflow_path = Path(path)
    workflow, raw = load_workflow(workflow_path)
    nodes = _nodes(workflow)
    models, model_warnings = _declared_models(workflow, nodes)
    custom_nodes, node_warnings = _custom_nodes(nodes)
    references, reference_warnings = _referenced_models(nodes)
    note_urls, note_warnings = _note_urls_by_basename(nodes)
    extra_models, unresolved, bind_warnings = _bind_note_models(
        references,
        models,
        note_urls,
    )
    if extra_models:
        merged = {(model["category"], model["filename"]): model for model in models}
        for model in extra_models:
            merged[(model["category"], model["filename"])] = model
        models = [merged[key] for key in sorted(merged)]

    warnings = [
        *model_warnings,
        *node_warnings,
        *reference_warnings,
        *note_warnings,
        *bind_warnings,
    ]
    return {
        "schema": WORKFLOW_LOCK_SCHEMA,
        "workflow": {
            "name": workflow_path.name,
            "sha256": _sha256_bytes(raw),
        },
        "models": models,
        "custom_nodes": custom_nodes,
        "unresolved": unresolved,
        "warnings": warnings,
    }


def validate_workflow_lock(lock: Mapping[str, Any], *, require_resolved: bool = False) -> None:
    if lock.get("schema") != WORKFLOW_LOCK_SCHEMA:
        raise WorkflowResolutionError(
            f"Unsupported workflow lock schema: {lock.get('schema')!r}."
        )
    if not isinstance(lock.get("models"), list) or not isinstance(lock.get("custom_nodes"), list):
        raise WorkflowResolutionError("Workflow lock requires models and custom_nodes arrays.")
    unresolved = lock.get("unresolved")
    if not isinstance(unresolved, list):
        raise WorkflowResolutionError("Workflow lock requires an unresolved array.")
    warnings = lock.get("warnings", [])
    if warnings is not None and not isinstance(warnings, list):
        raise WorkflowResolutionError("Workflow lock warnings must be an array when present.")

    destinations: set[tuple[str, str]] = set()
    for model in lock["models"]:
        if not isinstance(model, Mapping):
            raise WorkflowResolutionError("Each locked model must be an object.")
        category = model.get("category")
        filename = model.get("filename")
        if category not in MODEL_DIRS or not isinstance(filename, str):
            raise WorkflowResolutionError("Locked model has an invalid category or filename.")
        try:
            normalized_filename = canonical_relpath(
                filename,
                category=str(category),
                field="locked model filename",
            )
        except PathError as exc:
            raise WorkflowResolutionError(str(exc)) from exc
        model["filename"] = normalized_filename
        _model_url(model.get("url"))
        sha256 = model.get("sha256")
        if sha256 is not None and (not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256)):
            raise WorkflowResolutionError("Locked model SHA256 is invalid.")
        destination = (category, normalized_filename)
        if destination in destinations:
            raise WorkflowResolutionError(
                f"Duplicate locked model destination: models/{category}/{normalized_filename}"
            )
        destinations.add(destination)

    node_ids: set[str] = set()
    for node in lock["custom_nodes"]:
        if not isinstance(node, Mapping) or not isinstance(node.get("id"), str):
            raise WorkflowResolutionError("Each locked custom node requires an id.")
        node_id = node["id"]
        if not CNR_ID_RE.fullmatch(node_id):
            raise WorkflowResolutionError(f"Invalid Comfy Registry id: {node_id!r}")
        version = node.get("version")
        if version is not None and (not isinstance(version, str) or len(version) > 128):
            raise WorkflowResolutionError(f"Invalid version for custom node {node_id!r}.")
        if node_id in node_ids:
            raise WorkflowResolutionError(f"Duplicate custom node id: {node_id!r}")
        node_ids.add(node_id)
        url = node.get("url")
        if url is not None:
            if not isinstance(url, str) or not url.startswith("https://github.com/"):
                raise WorkflowResolutionError(
                    f"Custom node {node_id!r} url must be an https://github.com/ repository."
                )
            if ".." in url or " " in url:
                raise WorkflowResolutionError(f"Unsafe custom node url for {node_id!r}.")

    if require_resolved and unresolved:
        names = ", ".join(str(item.get("filename", "unknown")) for item in unresolved)
        raise WorkflowResolutionError(f"Workflow still has unresolved model dependencies: {names}")


def load_workflow_lock(path: str | Path, *, require_resolved: bool = False) -> dict[str, Any]:
    lock = _json_object(Path(path).read_bytes(), source=str(path))
    validate_workflow_lock(lock, require_resolved=require_resolved)
    return lock


def workflow_file_sha256(path: str | Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def lock_matches_workflow(lock: Mapping[str, Any], workflow_path: str | Path) -> bool:
    recorded = (lock.get("workflow") or {}).get("sha256") if isinstance(lock, Mapping) else None
    if not isinstance(recorded, str) or not recorded:
        return False
    return recorded == workflow_file_sha256(workflow_path)


def select_workflow_lock(
    workflow_path: str | Path,
    lock_path: str | Path,
) -> tuple[dict[str, Any], str]:
    """Pick a lock that still matches the workflow JSON.

    Reuse a fully resolved on-disk lock when its ``workflow.sha256`` matches.
    That keeps curated locks (LTX-2.5) from being overwritten by a noisy
    re-resolve. If the JSON changed, resolve again — but never replace a
    curated resolved lock with an unresolved auto-resolve.
    """
    workflow_path = Path(workflow_path)
    lock_path = Path(lock_path)
    existing: dict[str, Any] | None = None
    if lock_path.is_file():
        try:
            existing = load_workflow_lock(lock_path, require_resolved=False)
        except (WorkflowResolutionError, OSError):
            existing = None

    if existing is not None and lock_matches_workflow(existing, workflow_path):
        validate_workflow_lock(existing, require_resolved=True)
        return existing, "reused"

    fresh = resolve_workflow(workflow_path)
    existing_is_curated = bool(
        existing is not None
        and not existing.get("unresolved")
        and existing.get("models")
    )
    if existing_is_curated and fresh.get("unresolved"):
        raise WorkflowResolutionError(
            f"{workflow_path} changed (sha256 mismatch) but auto-resolve still "
            f"has unresolved models. Update {lock_path} by hand; hydrate will "
            "not overwrite a curated resolved lock with an incomplete resolve."
        )
    validate_workflow_lock(fresh, require_resolved=True)
    return fresh, "resolved"


def dump_workflow_lock(lock: Mapping[str, Any], output_path: str | Path) -> dict[str, Any]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    payload = dict(lock)
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    return payload


def write_workflow_lock(workflow_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    return dump_workflow_lock(resolve_workflow(workflow_path), output_path)
