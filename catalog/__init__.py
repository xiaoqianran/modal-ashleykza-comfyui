"""Product recipes: UI contract + hydrate paths. Not a per-workflow Python adapter.

Two execution modes:

- ``graph``: catalog embeds a ComfyUI API prompt with ``$placeholders``.
  Use only when the Image is missing nodes from the official UI JSON (Z-Image).
- ``workflow``: official UI JSON + ``graphToPrompt()`` + bind by node class.
  This is the default for new recipes (Pixal3D / TripoSplat).
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = Path(__file__).resolve().parent

PLACEHOLDER_PREFIX = "$"
DEFAULT_CATALOG_ID = "z-image"
CATALOG_SCHEMA = 1
PARAM_TYPES = {"text", "int", "float", "image"}
CATALOG_KINDS = {"t2i", "i2i", "i23d", "t2v", "i2v", "other"}
CATALOG_MODES = {"graph", "workflow"}
KNOWN_BINDS = {
    "prompt",
    "negative",
    "seed",
    "steps",
    "cfg",
    "width",
    "height",
    "image",
    "filename_prefix",
}
PUBLIC_KEYS = (
    "schema",
    "id",
    "title",
    "summary",
    "kind",
    "mode",
    "gpu",
    "gpu_choices",
    "params",
    "io",
    "client_id",
    "filename_prefix",
)


def catalog_path(recipe_id: str) -> Path:
    safe = Path(recipe_id).name
    path = CATALOG_DIR / f"{safe}.json"
    if path.resolve().parent != CATALOG_DIR.resolve():
        raise ValueError(f"invalid catalog id: {recipe_id!r}")
    return path


def _repo_file(relative: str, *, field: str) -> Path:
    raw = Path(str(relative))
    if raw.is_absolute() or any(part in {"", ".", ".."} for part in raw.parts):
        raise ValueError(f"unsafe {field}: {relative!r}")
    path = (ROOT / raw).resolve()
    if ROOT.resolve() not in path.parents:
        raise ValueError(f"{field} escapes the repository: {relative!r}")
    if not path.is_file():
        raise ValueError(f"{field} not found: {relative}")
    return path


def catalog_mode(catalog: dict[str, Any]) -> str:
    mode = catalog.get("mode")
    if mode in CATALOG_MODES:
        return str(mode)
    return "graph" if isinstance(catalog.get("graph"), dict) else "workflow"


def has_param(catalog: dict[str, Any], param_id: str) -> bool:
    return any(str(spec.get("id")) == param_id for spec in catalog.get("params") or ())


def image_params(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    return [spec for spec in catalog.get("params") or () if spec.get("type") == "image"]


def catalog_io(catalog: dict[str, Any]) -> dict[str, Any]:
    images = image_params(catalog)
    declared = catalog.get("io") if isinstance(catalog.get("io"), dict) else {}
    return {
        "images_in": int(declared.get("images_in") or len(images)),
        "images_required": sum(1 for spec in images if spec.get("required")),
        "prompt": has_param(catalog, "prompt"),
        "negative": has_param(catalog, "negative"),
    }


def validate_catalog(payload: dict[str, Any]) -> dict[str, Any]:
    schema = payload.get("schema", CATALOG_SCHEMA)
    if schema != CATALOG_SCHEMA:
        raise ValueError(f"unsupported catalog schema: {schema!r}")
    for key in ("id", "title", "workflow", "lock", "gpu"):
        if not str(payload.get(key) or "").strip():
            raise ValueError(f"catalog missing {key}")
    recipe_id = str(payload["id"])
    _repo_file(str(payload["workflow"]), field="workflow")
    _repo_file(str(payload["lock"]), field="lock")
    kind = payload.get("kind") or "other"
    if kind not in CATALOG_KINDS:
        raise ValueError(f"unsupported catalog kind: {kind!r}")
    mode = catalog_mode(payload)
    if mode not in CATALOG_MODES:
        raise ValueError(f"unsupported catalog mode: {mode!r}")
    if mode == "graph" and not isinstance(payload.get("graph"), dict):
        raise ValueError(f"catalog {recipe_id!r} mode=graph requires an API prompt graph")
    choices = list(payload.get("gpu_choices") or (payload["gpu"],))
    if payload["gpu"] not in choices:
        raise ValueError(f"catalog gpu {payload['gpu']!r} is not in gpu_choices")
    seen: set[str] = set()
    for spec in payload.get("params") or ():
        if not isinstance(spec, dict) or not spec.get("id"):
            raise ValueError("each catalog param needs an id")
        param_id = str(spec["id"])
        if param_id in seen:
            raise ValueError(f"duplicate catalog param: {param_id}")
        seen.add(param_id)
        kind_name = str(spec.get("type") or "text")
        if kind_name not in PARAM_TYPES:
            raise ValueError(f"unsupported param type {kind_name!r} for {param_id}")
        bind = str(spec.get("bind") or param_id)
        if bind not in KNOWN_BINDS:
            raise ValueError(f"unsupported param bind {bind!r} for {param_id}")
        if kind_name == "image" and bind != "image":
            raise ValueError(f"image param {param_id} must bind=image")
    if mode == "graph" and image_params(payload):
        graph = payload["graph"]
        if not any(
            isinstance(node, dict) and node.get("class_type") == "LoadImage"
            for node in graph.values()
        ):
            raise ValueError(
                f"catalog {recipe_id!r} declares image params but graph has no LoadImage"
            )
    payload = dict(payload)
    payload["schema"] = CATALOG_SCHEMA
    payload["kind"] = kind
    payload["mode"] = mode
    payload["gpu_choices"] = choices
    payload["io"] = catalog_io(payload)
    return payload


def list_item(catalog: dict[str, Any]) -> dict[str, Any]:
    io = catalog_io(catalog)
    return {
        "id": catalog["id"],
        "title": catalog.get("title") or catalog["id"],
        "summary": catalog.get("summary") or "",
        "kind": catalog.get("kind") or "other",
        "mode": catalog_mode(catalog),
        "gpu": catalog.get("gpu"),
        "gpu_choices": list(catalog.get("gpu_choices") or ()),
        "io": io,
    }


def list_catalogs() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(CATALOG_DIR.glob("*.json")):
        items.append(list_item(load_catalog(path.stem)))
    items.sort(key=lambda item: (item["id"] != DEFAULT_CATALOG_ID, item["id"]))
    return items


def load_catalog(recipe_id: str) -> dict[str, Any]:
    path = catalog_path(recipe_id)
    if not path.is_file():
        raise FileNotFoundError(f"catalog not found: {recipe_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"catalog {recipe_id!r} must be a JSON object")
    if payload.get("id") != recipe_id:
        raise ValueError(f"catalog id mismatch: {payload.get('id')!r} != {recipe_id!r}")
    return validate_catalog(payload)


def public_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """Fields the browser needs. Never send the API graph."""
    public = {key: catalog[key] for key in PUBLIC_KEYS if key in catalog}
    public["mode"] = catalog_mode(catalog)
    public["defaults"] = param_defaults(catalog)
    public["io"] = catalog_io(catalog)
    public["has_graph"] = isinstance(catalog.get("graph"), dict)
    return public


def param_defaults(catalog: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for spec in catalog.get("params") or ():
        if spec.get("type") == "image":
            continue
        if "default" in spec:
            values[str(spec["id"])] = spec["default"]
    prefix = catalog.get("filename_prefix")
    if prefix:
        values.setdefault("filename_prefix", prefix)
    return values


def coerce_param(spec: dict[str, Any], raw: Any) -> Any:
    kind = str(spec.get("type") or "text")
    if kind == "image":
        if raw is None or str(raw).strip() == "":
            if spec.get("required"):
                raise ValueError(f"missing required param: {spec['id']}")
            return None
        return str(raw)
    if raw is None:
        if spec.get("required"):
            raise ValueError(f"missing required param: {spec['id']}")
        return spec.get("default")
    if kind == "int":
        value = int(raw)
    elif kind == "float":
        value = float(raw)
    else:
        value = str(raw)
    minimum = spec.get("minimum")
    maximum = spec.get("maximum")
    if isinstance(value, int | float):
        if minimum is not None and value < minimum:
            raise ValueError(f"{spec['id']} must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"{spec['id']} must be <= {maximum}")
    return value


def bind_values(catalog: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    values = param_defaults(catalog)
    specs = {str(spec["id"]): spec for spec in catalog.get("params") or ()}
    for key, raw in (overrides or {}).items():
        if key == "filename_prefix":
            values[key] = str(raw)
            continue
        spec = specs.get(key)
        if spec is None or spec.get("type") == "image":
            continue
        values[key] = coerce_param(spec, raw)
    for spec in catalog.get("params") or ():
        if spec.get("type") == "image":
            continue
        if spec.get("required") and not str(values.get(spec["id"]) or "").strip():
            raise ValueError(f"missing required param: {spec['id']}")
    seed = values.get("seed")
    if seed == -1:
        values["seed"] = random.randint(0, 2**31 - 1)
    values.setdefault("filename_prefix", catalog.get("filename_prefix") or catalog["id"])
    return values


def _replace(node: Any, values: dict[str, Any]) -> Any:
    if isinstance(node, str) and node.startswith(PLACEHOLDER_PREFIX):
        key = node[len(PLACEHOLDER_PREFIX) :]
        if key not in values:
            raise KeyError(f"unbound catalog placeholder: {node}")
        return values[key]
    if isinstance(node, dict):
        return {key: _replace(value, values) for key, value in node.items()}
    if isinstance(node, list):
        return [_replace(value, values) for value in node]
    return node


def bind_graph(
    catalog: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    values = bind_values(catalog, overrides)
    graph = catalog.get("graph")
    if not isinstance(graph, dict):
        raise ValueError(f"catalog {catalog.get('id')!r} has no prompt graph")
    return _replace(graph, values), values


def apply_workflow_binds(
    prompt: dict[str, Any],
    catalog: dict[str, Any],
    values: dict[str, Any],
    *,
    image_name: str | None = None,
) -> dict[str, Any]:
    """Bind a converted API prompt using catalog params. No per-recipe Python."""
    import workflow_queue

    graph = json.loads(json.dumps(prompt))
    text = values.get("prompt") if has_param(catalog, "prompt") else None
    negative = values.get("negative") if has_param(catalog, "negative") else None
    if text is not None or negative is not None:
        workflow_queue.bind_text_prompt(graph, text=text, negative=negative)
    workflow_queue.bind_number_inputs(graph, values)
    prefix = values.get("filename_prefix")
    if prefix:
        workflow_queue.bind_filename_prefix(graph, str(prefix))
    if image_name:
        workflow_queue.bind_load_image(graph, image_name)
    elif image_params(catalog) and any(spec.get("required") for spec in image_params(catalog)):
        raise ValueError(f"catalog {catalog.get('id')!r} requires an input image")
    return graph


def build_prompt(
    catalog: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    *,
    api_prompt: dict[str, Any] | None = None,
    image_name: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    values = bind_values(catalog, overrides)
    if catalog_mode(catalog) == "graph":
        graph, values = bind_graph(catalog, overrides)
        if image_name:
            import workflow_queue

            workflow_queue.bind_load_image(graph, image_name)
        return graph, values
    if not api_prompt:
        raise ValueError(
            f"catalog {catalog.get('id')!r} mode=workflow needs a converted API prompt"
        )
    return apply_workflow_binds(api_prompt, catalog, values, image_name=image_name), values


def workflow_path(catalog: dict[str, Any]) -> Path:
    return _repo_file(str(catalog["workflow"]), field="workflow")


def lock_path(catalog: dict[str, Any]) -> Path:
    return _repo_file(str(catalog["lock"]), field="lock")
