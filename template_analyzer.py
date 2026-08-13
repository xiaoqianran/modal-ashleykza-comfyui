"""Classify Comfy-Org workflow_templates JSON for local hydrate / GPU.

Does not download weights or start a GPU. Point ``--dir`` at a JSON-only
checkout of https://github.com/Comfy-Org/workflow_templates/tree/main/templates
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import workflow_resolver
from workflow_queue import inspect_workflow

INDEX_NAMES = {"index.json"}
SKIP_PREFIXES = ("index.",)


def load_catalog(templates_dir: Path) -> dict[str, dict[str, Any]]:
    path = templates_dir / "index.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    catalog: dict[str, dict[str, Any]] = {}
    if not isinstance(payload, list):
        return catalog
    for module in payload:
        if not isinstance(module, dict):
            continue
        for item in module.get("templates") or ():
            if not isinstance(item, dict) or not item.get("name"):
                continue
            catalog[str(item["name"])] = {
                "title": item.get("title"),
                "openSource": item.get("openSource"),
                "vram": item.get("vram"),
                "models": list(item.get("models") or ()),
                "tags": list(item.get("tags") or ()),
                "type": module.get("type"),
                "io": item.get("io") or {},
            }
    return catalog


def iter_workflow_json(templates_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(templates_dir.glob("*.json")):
        name = path.name
        if name in INDEX_NAMES or name.startswith(SKIP_PREFIXES):
            continue
        files.append(path)
    return files


def _vram_gb(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return 0.0
    if value > 1000:
        return round(value / 1e9, 1)
    return round(value, 1)


def classify_workflow(
    path: Path,
    *,
    catalog: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    stem = path.stem
    meta = (catalog or {}).get(stem, {})
    record: dict[str, Any] = {
        "file": path.name,
        "id": stem,
        "title": meta.get("title"),
        "openSource": meta.get("openSource"),
        "type": meta.get("type"),
        "tags": meta.get("tags") or [],
        "vram_gb": _vram_gb(meta.get("vram")),
        "api": stem.startswith("api_"),
        "bucket": "parse_fail",
    }
    try:
        inspect = inspect_workflow(json.loads(path.read_text(encoding="utf-8")))
        record["format"] = inspect.get("format")
        record["binds"] = dict(
            Counter(item.get("bind") for item in inspect.get("nodes") or ())
        )
        record["n_nodes"] = len(inspect.get("nodes") or ())
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        record["inspect_error"] = str(exc)
    try:
        lock = workflow_resolver.resolve_workflow(path)
    except workflow_resolver.WorkflowResolutionError as exc:
        record["error"] = str(exc)
        if record["api"]:
            record["bucket"] = "api_cloud"
        return record

    models = lock.get("models") or []
    unresolved = lock.get("unresolved") or []
    custom = lock.get("custom_nodes") or []
    record["n_models"] = len(models)
    record["n_urls"] = sum(1 for model in models if model.get("url"))
    record["n_unresolved"] = len(unresolved)
    record["n_custom"] = len(custom)
    record["custom_ids"] = [node.get("id") for node in custom]
    record["unresolved"] = [item.get("filename") for item in unresolved[:12]]
    record["models"] = [
        {"filename": model.get("filename"), "category": model.get("category")}
        for model in models[:12]
    ]

    if record["api"]:
        record["bucket"] = "api_cloud"
    elif custom:
        record["bucket"] = "needs_cnr"
    elif unresolved:
        record["bucket"] = "unresolved_models"
    elif not models:
        record["bucket"] = "core_no_weights"
    elif record["n_urls"] == record["n_models"]:
        record["bucket"] = "hydrate_ready"
    else:
        record["bucket"] = "models_no_url"
    return record


def scan_templates(templates_dir: Path) -> dict[str, Any]:
    templates_dir = Path(templates_dir)
    catalog = load_catalog(templates_dir)
    rows = [
        classify_workflow(path, catalog=catalog)
        for path in iter_workflow_json(templates_dir)
    ]
    buckets = Counter(row["bucket"] for row in rows)
    smoke = [
        row
        for row in rows
        if row["bucket"] == "hydrate_ready"
        and isinstance(row.get("vram_gb"), int | float)
        and 0 < float(row["vram_gb"]) <= 16
        and not row["api"]
    ]
    smoke.sort(key=lambda row: (row.get("vram_gb") is None, row.get("vram_gb") or 0, row["file"]))
    return {
        "dir": str(templates_dir),
        "count": len(rows),
        "buckets": dict(buckets),
        "feasible": buckets.get("hydrate_ready", 0) + buckets.get("core_no_weights", 0),
        "smoke": smoke[:25],
        "rows": rows,
    }


def render_summary(report: dict[str, Any]) -> str:
    lines = [
        f"scanned {report['count']} JSON under {report['dir']}",
        f"buckets {report['buckets']}",
        f"locally feasible (hydrate_ready + core_no_weights) {report['feasible']}",
        "cheapest hydrate_ready smoke (vram <= 16GB):",
    ]
    for row in report.get("smoke") or ():
        lines.append(
            f"  {row.get('vram_gb')}GB  {row['file']}  models={row.get('n_models')}  {row.get('title')}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Classify Comfy-Org workflow template JSON without starting a GPU.",
    )
    parser.add_argument(
        "--dir",
        required=True,
        help="directory of *.json (sparse-clone templates/, JSON only)",
    )
    parser.add_argument("--out", default="", help="write full JSON report")
    parser.add_argument("--file", default="", help="classify a single workflow")
    args = parser.parse_args(argv)
    templates_dir = Path(args.dir)
    if args.file:
        catalog = load_catalog(templates_dir)
        record = classify_workflow(Path(args.file), catalog=catalog)
        print(json.dumps(record, indent=2, ensure_ascii=False))
        return
    report = scan_templates(templates_dir)
    print(render_summary(report), end="")
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
