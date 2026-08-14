"""Create / update the private Hugging Face dataset."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from gallery_hub import BUCKETS, DEFAULT_REPO, build_index, write_json
from gallery_hub.stage import DATASET_CARD, load_items, stage_collection


def _api(token: str | None = None):
    from huggingface_hub import HfApi

    return HfApi(token=token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"))


def ensure_repo(repo: str, *, private: bool = True, token: str | None = None) -> None:
    api = _api(token)
    api.create_repo(repo_id=repo, repo_type="dataset", private=private, exist_ok=True)


def _ensure_bucket_placeholders(root: Path) -> None:
    for bucket in BUCKETS:
        readme = root / bucket / "README.md"
        if readme.is_file():
            continue
        titles = {"image": "图片模型", "video": "视频模型", "mesh3d": "3D 模型"}
        readme.parent.mkdir(parents=True, exist_ok=True)
        readme.write_text(
            f"# {titles[bucket]}\n\n"
            f"按配方 id 建子目录，再按 collection 存放媒体 + 提示词 sidecar。\n",
            encoding="utf-8",
        )


def push_folder(local_root: Path, repo: str, *, token: str | None = None) -> None:
    from huggingface_hub import HfApi

    write_json(local_root / "dataset-index.json", build_index(local_root, repo=repo))
    card = local_root / "README.md"
    if not card.is_file():
        card.write_text(DATASET_CARD, encoding="utf-8")
    _ensure_bucket_placeholders(local_root)
    api = HfApi(token=token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"))
    api.upload_folder(
        repo_id=repo,
        repo_type="dataset",
        folder_path=str(local_root),
        commit_message="Update gallery collection",
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Stage a collection and push it to Hugging Face.")
    parser.add_argument("--repo", default=os.environ.get("HF_GALLERY_REPO") or DEFAULT_REPO)
    parser.add_argument("--recipe", required=True, help="catalog id, e.g. flux2-dev")
    parser.add_argument("--collection", required=True, help="slug, e.g. campus-days")
    parser.add_argument("--title", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--kind", default="t2i", help="catalog kind: t2i/i2i/t2v/i2v/i23d")
    parser.add_argument("--media-dir", default="")
    parser.add_argument("--timings", default="")
    parser.add_argument("--storyboard", default="")
    parser.add_argument("--stage", default="artifacts/hf-gallery-stage")
    parser.add_argument("--public", action="store_true", help="create the dataset as public (default private)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    media_dir = Path(args.media_dir) if args.media_dir else None
    timings = Path(args.timings) if args.timings else None
    storyboard = Path(args.storyboard) if args.storyboard else None
    items, meta = load_items(media_dir=media_dir, timings_path=timings, storyboard_path=storyboard)
    if not items:
        raise SystemExit("no media items found")
    title = args.title or meta.get("title") or args.collection
    summary = args.summary or meta.get("summary") or ""
    stage_root = Path(args.stage)
    if not args.dry_run:
        ensure_repo(args.repo, private=not args.public)
        try:
            from gallery_hub.pull import pull

            pull(args.repo, stage_root)
        except Exception as exc:
            print(f"pull skipped ({exc}); staging into empty folder")
            stage_root.mkdir(parents=True, exist_ok=True)
    folder = stage_collection(
        dest_root=stage_root,
        recipe=args.recipe,
        collection=args.collection,
        title=title,
        kind=args.kind,
        summary=summary,
        items=items,
        extra={"source": meta.get("source")},
    )
    print(f"staged {len(items)} items -> {folder}")
    if args.dry_run:
        return
    push_folder(stage_root, args.repo)
    print(f"pushed {args.repo}")


if __name__ == "__main__":
    main()
