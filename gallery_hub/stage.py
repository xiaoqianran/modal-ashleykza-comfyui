"""Assemble a collection folder (media + prompt sidecars) ready to push."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from gallery_hub import (
    SCHEMA,
    bucket_for_kind,
    collection_dir,
    collection_payload,
    item_stem,
    sidecar_payload,
    slug,
    write_json,
)


def _load_optional_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def items_from_timings(timings: dict[str, Any]) -> list[dict[str, Any]]:
    frames = timings.get("frames") or timings.get("items") or []
    items: list[dict[str, Any]] = []
    for frame in frames:
        images = frame.get("images") or []
        media = Path(str(images[0])) if images else None
        if media is None or not media.is_file():
            continue
        extra = {
            key: frame[key]
            for key in ("act", "act_title", "prompt_id", "seconds", "seed")
            if key in frame
        }
        items.append(
            {
                "id": str(frame.get("id") or media.stem),
                "title": str(frame.get("title") or frame.get("id") or media.stem),
                "prompt": str(frame.get("prompt") or frame.get("text") or ""),
                "media_path": media,
                "extra": extra,
            }
        )
    return items


def items_from_storyboard(
    storyboard: dict[str, Any],
    media_dir: Path,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for frame in storyboard.get("frames") or []:
        item_id = str(frame.get("id") or "").strip()
        if not item_id:
            continue
        matches = sorted(media_dir.glob(f"*{item_id}*"))
        if not matches:
            padded = item_id.zfill(5)
            matches = sorted(media_dir.glob(f"*{padded}*"))
        if not matches:
            continue
        extra = {key: frame[key] for key in ("act", "act_title") if key in frame}
        items.append(
            {
                "id": item_id,
                "title": str(frame.get("title") or item_id),
                "prompt": str(frame.get("text") or frame.get("prompt") or ""),
                "media_path": matches[0],
                "extra": extra,
            }
        )
    return items


def items_from_media_dir(media_dir: Path) -> list[dict[str, Any]]:
    files = sorted(
        path
        for path in media_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".glb", ".gltf"}
    )
    items: list[dict[str, Any]] = []
    for index, path in enumerate(files, start=1):
        sidecar = path.with_suffix(".json")
        prompt = ""
        title = path.stem
        extra: dict[str, Any] = {}
        if sidecar.is_file():
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            prompt = str(data.get("prompt") or data.get("text") or "")
            title = str(data.get("title") or title)
            extra = dict(data.get("extra") or {})
        items.append(
            {
                "id": f"{index:03d}",
                "title": title,
                "prompt": prompt,
                "media_path": path,
                "extra": extra,
            }
        )
    return items


def stage_collection(
    *,
    dest_root: Path,
    recipe: str,
    collection: str,
    title: str,
    kind: str = "t2i",
    summary: str = "",
    items: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> Path:
    bucket = bucket_for_kind(kind)
    recipe_id = slug(recipe)
    collection_id = slug(collection)
    folder = collection_dir(dest_root, bucket, recipe_id, collection_id)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)

    staged: list[dict[str, Any]] = []
    for item in items:
        stem = item_stem(str(item["id"]))
        source = Path(item["media_path"])
        media_name = f"{stem}{source.suffix.lower()}"
        shutil.copy2(source, folder / media_name)
        sidecar = sidecar_payload(
            item_id=str(item["id"]),
            media_name=media_name,
            prompt=str(item.get("prompt") or ""),
            title=str(item.get("title") or item["id"]),
            recipe=recipe_id,
            collection=collection_id,
            bucket=bucket,
            extra=item.get("extra") or None,
        )
        write_json(folder / f"{stem}.json", sidecar)
        staged.append(sidecar)

    write_json(
        folder / "collection.json",
        collection_payload(
            collection_id=collection_id,
            title=title,
            recipe=recipe_id,
            bucket=bucket,
            summary=summary,
            items=staged,
            extra=extra,
        ),
    )
    return folder


def load_items(
    *,
    media_dir: Path | None = None,
    timings_path: Path | None = None,
    storyboard_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    timings = _load_optional_json(timings_path)
    storyboard = _load_optional_json(storyboard_path)
    if timings:
        items = items_from_timings(timings)
        meta = {
            "title": timings.get("storyboard") or storyboard.get("title") or "",
            "summary": (timings.get("flux2_notes") or {}).get("style") or storyboard.get("summary") or "",
            "source": "timings",
        }
        return items, meta
    if storyboard and media_dir:
        items = items_from_storyboard(storyboard, media_dir)
        meta = {
            "title": storyboard.get("title") or "",
            "summary": storyboard.get("summary") or "",
            "source": "storyboard",
        }
        return items, meta
    if media_dir:
        return items_from_media_dir(media_dir), {"title": "", "summary": "", "source": "media-dir"}
    raise ValueError("need --timings, or --storyboard plus --media-dir, or --media-dir")


DATASET_CARD = f"""---
license: other
pretty_name: Modal ComfyUI Picture
tags:
  - comfyui
  - modal
  - image-generation
  - video-generation
  - 3d
---

# modal-comfyui-picture

Private gallery for [xiaoqianran/modal-ashleykza-comfyui](https://github.com/xiaoqianran/modal-ashleykza-comfyui).
GitHub never stores the binaries. Pages builds pull this dataset on a schedule.

## Layout

```text
image/     # t2i / i2i   → PNG/JPEG/WebP + sidecar JSON (prompt)
video/     # t2v / i2v   → MP4/WebM + sidecar JSON
mesh3d/    # i23d        → GLB/GLTF/splat + sidecar JSON
  <recipe-id>/
    <collection-id>/
      collection.json
      001.png
      001.json
```

Each sidecar is schema {SCHEMA}: `id`, `title`, `prompt`, `media`, `recipe`, `collection`.
`dataset-index.json` at the repo root lists every collection.

## Visibility

The Hugging Face dataset is **private**. Copying files into GitHub Pages makes that
snapshot visible on the public docs site. Do not upload anything that must stay private.
"""
