"""Scaffold a Studio recipe: workflow + lock + catalog + overlay stub.

Happy path only (``mode=workflow``). Does not guess HuggingFace URLs, does not
write ``queue_*.py``, and does not add ``mode=graph``.

    python3 -m recipe_scaffold path/to/official.json --id my-recipe --title "My Recipe" --kind t2i
    python3 -m recipe_scaffold path/to/official.json --id my-recipe --title "My Recipe" --kind i23d --write
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from catalog import CATALOG_KINDS, ROOT
from catalog.gates import (
    FORBIDDEN_GPUS,
    GRAPH_MODE_IDS,
    INFERENCE_GPU,
    NON_L40S_DEFAULT_GPU_IDS,
    TEST_GPU,
    enforce_recipe_gates,
    validate_recipe_id,
)
from workflow_resolver import dump_workflow_lock, resolve_workflow


@dataclass
class ScaffoldResult:
    recipe_id: str
    workflow: Path
    lock: Path
    catalog: Path
    catalog_payload: dict[str, Any]
    lock_payload: dict[str, Any]
    overlay_stub: dict[str, Any]
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    wrote: bool = False
    overlay_wrote: bool = False

    @property
    def resolved(self) -> bool:
        return not self.unresolved


def default_params(kind: str) -> list[dict[str, Any]]:
    prompt = {
        "id": "prompt",
        "type": "text",
        "bind": "prompt",
        "title": "提示词",
        "required": True,
    }
    image = {
        "id": "image",
        "type": "image",
        "bind": "image",
        "title": "输入图",
        "required": True,
    }
    seed = {
        "id": "seed",
        "type": "int",
        "bind": "seed",
        "title": "种子",
        "default": -1,
        "minimum": -1,
    }
    if kind in {"i23d"}:
        return [image]
    if kind in {"i2i", "i2v"}:
        return [image, prompt, seed]
    return [prompt, seed]


def build_catalog_draft(
    *,
    recipe_id: str,
    title: str,
    kind: str,
    workflow: str,
    lock: str,
    summary: str = "",
    gpu: str = TEST_GPU,
) -> dict[str, Any]:
    recipe_id = validate_recipe_id(recipe_id)
    if kind not in CATALOG_KINDS:
        raise ValueError(f"unsupported catalog kind: {kind!r}")
    if gpu in FORBIDDEN_GPUS:
        raise ValueError(f"gpu {gpu!r} is forbidden")
    if gpu != TEST_GPU and recipe_id not in NON_L40S_DEFAULT_GPU_IDS:
        allowed = ", ".join(sorted(NON_L40S_DEFAULT_GPU_IDS))
        raise ValueError(
            f"test gpu {gpu!r} is gated. Use {TEST_GPU}, or add {recipe_id!r} to "
            f"catalog.gates.NON_L40S_DEFAULT_GPU_IDS ({allowed}) with a PR reason."
        )
    choices = [gpu]
    if gpu != INFERENCE_GPU:
        choices.append(INFERENCE_GPU)
    payload = {
        "schema": 1,
        "id": recipe_id,
        "title": title.strip() or recipe_id,
        "summary": summary.strip()
        or f"{title.strip() or recipe_id}。测试默认 {gpu}，正式推理 {INFERENCE_GPU}。不要用 T4。",
        "kind": kind,
        "mode": "workflow",
        "workflow": workflow,
        "lock": lock,
        "gpu": gpu,
        "gpu_inference": INFERENCE_GPU,
        "gpu_choices": choices,
        "client_id": f"studio-{recipe_id}",
        "filename_prefix": recipe_id.replace(".", "_"),
        "params": default_params(kind),
    }
    enforce_recipe_gates(payload)
    return payload


def build_overlay_stub(recipe_id: str, *, family: str = "") -> dict[str, Any]:
    recipe_id = validate_recipe_id(recipe_id)
    return {
        "id": recipe_id,
        "family": family or recipe_id.split("-")[0],
        "quant": None,
        "weights_gb": None,
        "vram_gb": None,
        "weights_note": "scaffold: fill after hydrate. Resolver does not guess URLs.",
        "shared_weights_with": [],
        "nodes": "core",
        "output": "",
        "smoke": {
            "status": "pending",
            "note": "scaffold; not timed. Stop modal serve after smoke.",
        },
    }


def _rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _copy_workflow(source: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != dest.resolve():
        shutil.copy2(source, dest)
    return dest


def append_overlay_stub(overlay_path: Path, stub: dict[str, Any]) -> None:
    payload = json.loads(overlay_path.read_text(encoding="utf-8"))
    models = payload.get("models")
    if not isinstance(models, list):
        raise ValueError(f"{overlay_path} needs a models list")
    recipe_id = stub["id"]
    if any(str(item.get("id")) == recipe_id for item in models if isinstance(item, dict)):
        raise ValueError(f"overlay already has id {recipe_id!r}")
    models.append(stub)
    overlay_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def scaffold(
    source: Path,
    *,
    recipe_id: str,
    title: str,
    kind: str,
    summary: str = "",
    gpu: str = TEST_GPU,
    family: str = "",
    root: Path | None = None,
    write: bool = False,
    write_overlay: bool = False,
    force: bool = False,
) -> ScaffoldResult:
    root = (root or ROOT).resolve()
    recipe_id = validate_recipe_id(recipe_id)
    if recipe_id in GRAPH_MODE_IDS:
        raise ValueError(
            f"{recipe_id!r} is a gated mode=graph exception. Scaffold only writes "
            "mode=workflow recipes."
        )
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"workflow not found: {source}")

    examples = root / "examples"
    workflow_dest = examples / source.name
    lock_dest = examples / f"{source.stem}.lock.json"
    catalog_dest = root / "catalog" / f"{recipe_id}.json"
    if write and not force:
        for path in (catalog_dest, lock_dest):
            if path.is_file():
                raise FileExistsError(f"{path} exists; pass --force to overwrite")
        if workflow_dest.is_file() and workflow_dest.resolve() != source.resolve():
            raise FileExistsError(f"{workflow_dest} exists; pass --force to overwrite")

    lock_payload = resolve_workflow(source)
    catalog_payload = build_catalog_draft(
        recipe_id=recipe_id,
        title=title,
        kind=kind,
        workflow=_rel(workflow_dest, root) if write else f"examples/{source.name}",
        lock=_rel(lock_dest, root) if write else f"examples/{source.stem}.lock.json",
        summary=summary,
        gpu=gpu,
    )
    overlay_stub = build_overlay_stub(recipe_id, family=family)
    result = ScaffoldResult(
        recipe_id=recipe_id,
        workflow=workflow_dest,
        lock=lock_dest,
        catalog=catalog_dest,
        catalog_payload=catalog_payload,
        lock_payload=lock_payload,
        overlay_stub=overlay_stub,
        unresolved=list(lock_payload.get("unresolved") or ()),
        warnings=list(lock_payload.get("warnings") or ()),
    )
    if not write:
        return result

    _copy_workflow(source, workflow_dest)
    catalog_dest.parent.mkdir(parents=True, exist_ok=True)
    dump_workflow_lock(lock_payload, lock_dest)
    catalog_dest.write_text(
        json.dumps(catalog_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result.wrote = True
    if write_overlay:
        append_overlay_stub(root / "benchmarks" / "models.json", overlay_stub)
        result.overlay_wrote = True
    return result


def _print_report(result: ScaffoldResult) -> None:
    print(f"id:        {result.recipe_id}")
    print("mode:      workflow")
    print(f"workflow:  {result.workflow}")
    print(f"lock:      {result.lock}")
    print(f"catalog:   {result.catalog}")
    print(f"models:    {len(result.lock_payload.get('models') or ())}")
    print(f"cnr:       {len(result.lock_payload.get('custom_nodes') or ())}")
    print(f"unresolved:{len(result.unresolved)}")
    if result.unresolved:
        print()
        print("UNRESOLVED (hand-fix the lock; resolver does not guess URLs):")
        for item in result.unresolved:
            name = item.get("filename") or item.get("name") or "?"
            reason = item.get("reason") or "missing_download_metadata"
            category = item.get("category") or "?"
            url = item.get("url") or ""
            extra = f" url={url}" if url else ""
            print(f"  - {category}/{name} ({reason}){extra}")
    if result.warnings:
        print()
        print("warnings:")
        for item in result.warnings:
            print(f"  - {item.get('code') or item}")
    print()
    print("catalog draft:")
    print(json.dumps(result.catalog_payload, indent=2, ensure_ascii=False))
    print()
    print("overlay stub (add to benchmarks/models.json, then python3 -m benchmarks --write):")
    print(json.dumps(result.overlay_stub, indent=2, ensure_ascii=False))
    if result.wrote:
        print()
        print("wrote catalog + lock" + (" + overlay" if result.overlay_wrote else ""))
        if not result.resolved:
            print(
                "lock still has unresolved models. Do not hydrate until URLs / "
                "MODEL_DIRS are filled in. Do not add a queue_*.py for this."
            )
        print("next: python3 -m benchmarks --write")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a mode=workflow Studio recipe. Does not write queue_*.py."
    )
    parser.add_argument("workflow", help="official ComfyUI UI JSON")
    parser.add_argument("--id", required=True, help="catalog id / filename")
    parser.add_argument("--title", default="", help="Studio display name")
    parser.add_argument("--kind", required=True, choices=sorted(CATALOG_KINDS))
    parser.add_argument("--summary", default="")
    parser.add_argument("--family", default="", help="overlay family label")
    parser.add_argument("--gpu", default=TEST_GPU, help=f"test default GPU (default {TEST_GPU})")
    parser.add_argument("--write", action="store_true", help="write examples/ catalog/ lock")
    parser.add_argument(
        "--write-overlay",
        action="store_true",
        help="also append the overlay stub to benchmarks/models.json",
    )
    parser.add_argument("--force", action="store_true", help="overwrite existing catalog/lock")
    parser.add_argument("--root", default="", help="repository root (tests)")
    args = parser.parse_args(argv)
    result = scaffold(
        Path(args.workflow),
        recipe_id=args.id,
        title=args.title or args.id,
        kind=args.kind,
        summary=args.summary,
        gpu=args.gpu,
        family=args.family,
        root=Path(args.root) if args.root else ROOT,
        write=args.write,
        write_overlay=args.write_overlay,
        force=args.force,
    )
    _print_report(result)
    if result.unresolved:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
