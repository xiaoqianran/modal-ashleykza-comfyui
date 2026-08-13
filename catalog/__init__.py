"""Product recipes: lock + GPU + user-facing params + API prompt graph."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = Path(__file__).resolve().parent

PLACEHOLDER_PREFIX = "$"


def catalog_path(recipe_id: str) -> Path:
    safe = Path(recipe_id).name
    path = CATALOG_DIR / f"{safe}.json"
    if path.resolve().parent != CATALOG_DIR.resolve():
        raise ValueError(f"invalid catalog id: {recipe_id!r}")
    return path


def list_catalogs() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(CATALOG_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        items.append(
            {
                "id": payload["id"],
                "title": payload.get("title") or payload["id"],
                "summary": payload.get("summary") or "",
                "gpu": payload.get("gpu"),
                "gpu_choices": list(payload.get("gpu_choices") or ()),
            }
        )
    return items


def load_catalog(recipe_id: str) -> dict[str, Any]:
    path = catalog_path(recipe_id)
    if not path.is_file():
        raise FileNotFoundError(f"catalog not found: {recipe_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("id") != recipe_id:
        raise ValueError(f"catalog id mismatch: {payload.get('id')!r} != {recipe_id!r}")
    return payload


def param_defaults(catalog: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for spec in catalog.get("params") or ():
        if "default" in spec:
            values[str(spec["id"])] = spec["default"]
    prefix = catalog.get("filename_prefix")
    if prefix:
        values.setdefault("filename_prefix", prefix)
    return values


def coerce_param(spec: dict[str, Any], raw: Any) -> Any:
    kind = str(spec.get("type") or "text")
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
        if spec is None:
            continue
        values[key] = coerce_param(spec, raw)
    for spec in catalog.get("params") or ():
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


def workflow_path(catalog: dict[str, Any]) -> Path:
    return ROOT / str(catalog["workflow"])


def lock_path(catalog: dict[str, Any]) -> Path:
    return ROOT / str(catalog["lock"])
