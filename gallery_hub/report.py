"""Print collection/item counts after an HF pull. Fail if the snapshot is empty."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from gallery_hub import DEFAULT_REPO, build_index


def report(
    root: Path,
    repo: str = DEFAULT_REPO,
    *,
    require_items: bool = False,
) -> dict[str, Any]:
    index = build_index(root, repo=repo)
    collections = int(index.get("collection_count") or 0)
    items = int(index.get("item_count") or 0)
    print(f"collections={collections} items={items} repo={repo}")
    for entry in index.get("collections") or []:
        print(
            f"  {entry['bucket']}/{entry['recipe']}/{entry['id']} "
            f"items={entry['item_count']}"
        )
    if require_items and items == 0:
        raise SystemExit(
            f"HF gallery {repo} produced 0 items; refusing to publish an empty snapshot"
        )
    return index


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Audit a pulled HF gallery snapshot.")
    parser.add_argument("--src", default=".cache/hf-gallery")
    parser.add_argument("--repo", default=os.environ.get("HF_GALLERY_REPO") or DEFAULT_REPO)
    parser.add_argument(
        "--require-items",
        action="store_true",
        help="Exit nonzero when item_count is 0 (used when HF_TOKEN is set).",
    )
    args = parser.parse_args(argv)
    report(Path(args.src), repo=args.repo, require_items=args.require_items)


if __name__ == "__main__":
    main()
