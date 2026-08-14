"""Hugging Face picture hub: layout, sidecars, and Pages gallery.

Source of truth is a private HF dataset. Git never stores the binaries.
GitHub Actions pull the dataset and copy a snapshot into the Pages artifact.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA = 1
DEFAULT_REPO = "seachen/modal-comfyui-picture"

# Top-level folders on the dataset. Catalog `kind` maps into these buckets.
BUCKETS = ("image", "video", "mesh3d")
KIND_TO_BUCKET = {
    "t2i": "image",
    "i2i": "image",
    "t2v": "video",
    "i2v": "video",
    "i23d": "mesh3d",
}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}
MESH_SUFFIXES = {".glb", ".gltf", ".obj", ".ply", ".splat", ".spz"}

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def bucket_for_kind(kind: str) -> str:
    bucket = KIND_TO_BUCKET.get(str(kind or "").strip())
    if bucket not in BUCKETS:
        raise ValueError(f"unsupported catalog kind {kind!r}; expected one of {sorted(KIND_TO_BUCKET)}")
    return bucket


def bucket_for_suffix(suffix: str) -> str:
    ext = suffix.lower()
    if ext in IMAGE_SUFFIXES:
        return "image"
    if ext in VIDEO_SUFFIXES:
        return "video"
    if ext in MESH_SUFFIXES:
        return "mesh3d"
    raise ValueError(f"unknown media suffix: {suffix}")


def slug(value: str) -> str:
    text = str(value or "").strip().lower().replace(" ", "-")
    text = re.sub(r"[^a-z0-9._-]+", "-", text).strip("-")
    if not text or not SLUG_RE.match(text):
        raise ValueError(f"invalid slug: {value!r}")
    return text


def collection_dir(root: Path, bucket: str, recipe: str, collection: str) -> Path:
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}")
    return root / bucket / slug(recipe) / slug(collection)


def item_stem(item_id: str) -> str:
    raw = str(item_id).strip()
    if not raw:
        raise ValueError("empty item id")
    return slug(raw) if re.search(r"[a-zA-Z]", raw) else raw.zfill(3)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sidecar_payload(
    *,
    item_id: str,
    media_name: str,
    prompt: str,
    title: str = "",
    recipe: str,
    collection: str,
    bucket: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "id": str(item_id),
        "title": title or str(item_id),
        "prompt": prompt,
        "media": media_name,
        "bucket": bucket,
        "recipe": recipe,
        "collection": collection,
    }
    if extra:
        payload["extra"] = extra
    return payload


def collection_payload(
    *,
    collection_id: str,
    title: str,
    recipe: str,
    bucket: str,
    summary: str = "",
    items: Iterable[dict[str, Any]] = (),
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records = list(items)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "id": collection_id,
        "title": title,
        "summary": summary,
        "bucket": bucket,
        "recipe": recipe,
        "item_count": len(records),
        "items": [
            {
                "id": item["id"],
                "title": item.get("title") or item["id"],
                "media": item["media"],
                "sidecar": f"{Path(item['media']).stem}.json",
            }
            for item in records
        ],
    }
    if extra:
        payload["extra"] = extra
    return payload


def scan_collections(root: Path) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if not root.is_dir():
        return found
    for bucket in BUCKETS:
        bucket_dir = root / bucket
        if not bucket_dir.is_dir():
            continue
        for recipe_dir in sorted(p for p in bucket_dir.iterdir() if p.is_dir()):
            for collection_path in sorted(p for p in recipe_dir.iterdir() if p.is_dir()):
                manifest = collection_path / "collection.json"
                if not manifest.is_file():
                    continue
                data = read_json(manifest)
                data.setdefault("bucket", bucket)
                data.setdefault("recipe", recipe_dir.name)
                data.setdefault("id", collection_path.name)
                data["path"] = str(collection_path.relative_to(root).as_posix())
                found.append(data)
    return found


def build_index(root: Path, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    collections = scan_collections(root)
    return {
        "schema": SCHEMA,
        "repo": repo,
        "buckets": list(BUCKETS),
        "collection_count": len(collections),
        "item_count": sum(int(item.get("item_count") or len(item.get("items") or [])) for item in collections),
        "collections": [
            {
                "bucket": item["bucket"],
                "recipe": item["recipe"],
                "id": item["id"],
                "title": item.get("title") or item["id"],
                "summary": item.get("summary") or "",
                "item_count": int(item.get("item_count") or len(item.get("items") or [])),
                "path": item["path"],
            }
            for item in collections
        ],
    }


def media_kind_from_name(name: str) -> str:
    return bucket_for_suffix(Path(name).suffix)
