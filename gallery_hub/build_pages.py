"""Render MkDocs gallery pages from a local HF dataset snapshot."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from gallery_hub import (
    BUCKETS,
    DEFAULT_REPO,
    IMAGE_SUFFIXES,
    MESH_SUFFIXES,
    VIDEO_SUFFIXES,
    scan_collections,
)

BUCKET_TITLES = {"image": "图片模型", "video": "视频模型", "mesh3d": "3D 模型"}
EMPTY_MARKDOWN = """图库还没有从 Hugging Face 拉到作品。

GitHub Actions 每小时拉取私有数据集 [`{repo}`](https://huggingface.co/datasets/{repo})，
再把快照编进 Pages。仓库 git 里不保存媒体文件。

本地预览：

```bash
export HF_TOKEN=hf_xxx
python -m gallery_hub.pull --out .cache/hf-gallery
python -m gallery_hub.build_pages --src .cache/hf-gallery
mkdocs serve
```
"""


def _thumb(src: Path, dest: Path, max_size: int = 640) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
    except ImportError:
        shutil.copy2(src, dest)
        return dest
    with Image.open(src) as image:
        image = image.convert("RGB")
        image.thumbnail((max_size, max_size))
        dest = dest.with_suffix(".jpg")
        image.save(dest, "JPEG", quality=82, optimize=True)
    return dest


def _copy_media(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def _rel(path: Path, start: Path) -> str:
    return path.relative_to(start).as_posix()


def _item_card(item: dict[str, Any], collection_dir: Path, dest_dir: Path, page_dir: Path) -> str:
    media_name = str(item.get("media") or "")
    src = collection_dir / media_name
    sidecar_path = collection_dir / f"{Path(media_name).stem}.json"
    sidecar: dict[str, Any] = {}
    if sidecar_path.is_file():
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    title = sidecar.get("title") or item.get("title") or item.get("id")
    prompt = str(sidecar.get("prompt") or "")
    suffix = Path(media_name).suffix.lower()
    lines = [f'<article class="gallery-card" id="item-{item.get("id")}">']
    if suffix in IMAGE_SUFFIXES and src.is_file():
        full = _copy_media(src, dest_dir / src.name)
        thumb = _thumb(src, dest_dir / f"{src.stem}.thumb.jpg")
        lines.append(
            f'<a href="{_rel(full, page_dir)}" target="_blank" rel="noopener">'
            f'<img src="{_rel(thumb, page_dir)}" alt="{_escape(str(title))}" loading="lazy"></a>'
        )
    elif suffix in VIDEO_SUFFIXES and src.is_file():
        full = _copy_media(src, dest_dir / src.name)
        lines.append(
            f'<video controls preload="metadata" src="{_rel(full, page_dir)}"></video>'
        )
    elif suffix in MESH_SUFFIXES and src.is_file():
        full = _copy_media(src, dest_dir / src.name)
        lines.append(f'<a class="gallery-download" href="{_rel(full, page_dir)}">下载 {src.name}</a>')
    if prompt:
        lines.append("<details><summary>提示词</summary>")
        lines.append(f"<pre>{_escape(prompt)}</pre>")
        lines.append("</details>")
    lines.append(f"<p><strong>{_escape(str(title))}</strong></p>")
    lines.append("</article>")
    return "\n".join(lines)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_generated(src: Path, docs_gallery: Path, repo: str) -> str:
    collections = scan_collections(src)
    media_root = docs_gallery / "media"
    if media_root.exists():
        shutil.rmtree(media_root)
    media_root.mkdir(parents=True, exist_ok=True)

    if not collections:
        return EMPTY_MARKDOWN.format(repo=repo)

    chunks = [
        f"数据源：私有数据集 [`{repo}`](https://huggingface.co/datasets/{repo})。"
        "下面是最近一次 Actions 拉取的快照，git 里没有这些文件。",
        "",
    ]
    by_bucket: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in BUCKETS}
    for item in collections:
        by_bucket.setdefault(item["bucket"], []).append(item)

    for bucket in BUCKETS:
        group = by_bucket.get(bucket) or []
        if not group:
            continue
        chunks.append(f"## {BUCKET_TITLES.get(bucket, bucket)}")
        chunks.append("")
        for collection in group:
            folder = src / collection["path"]
            chunks.append(f"### {collection.get('title') or collection['id']}")
            chunks.append("")
            chunks.append(
                f"`{collection['recipe']}` · `{collection['id']}` · {collection.get('item_count') or 0} 件"
            )
            if collection.get("summary"):
                chunks.append("")
                chunks.append(str(collection["summary"]))
            chunks.append("")
            chunks.append('<div class="gallery-grid" markdown="1">')
            chunks.append("")
            for entry in collection.get("items") or []:
                chunks.append(_item_card(entry, folder, media_root / collection["path"], docs_gallery))
                chunks.append("")
            chunks.append("</div>")
            chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def build_pages(*, src: Path, docs_gallery: Path, repo: str = DEFAULT_REPO) -> Path:
    docs_gallery.mkdir(parents=True, exist_ok=True)
    generated = render_generated(src, docs_gallery, repo)
    out = docs_gallery / "_generated.md"
    out.write_text(generated, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build docs/gallery/_generated.md from an HF snapshot.")
    parser.add_argument("--src", default=".cache/hf-gallery")
    parser.add_argument("--docs-gallery", default="docs/gallery")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    args = parser.parse_args(argv)
    path = build_pages(src=Path(args.src), docs_gallery=Path(args.docs_gallery), repo=args.repo)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
