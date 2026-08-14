"""Download the private gallery dataset for a Pages build."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from gallery_hub import DEFAULT_REPO


def pull(repo: str, dest: Path, *, token: str | None = None) -> Path:
    from huggingface_hub import snapshot_download

    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo,
        repo_type="dataset",
        local_dir=str(dest),
        token=token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"),
    )
    return dest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Pull seachen/modal-comfyui-picture for Pages.")
    parser.add_argument("--repo", default=os.environ.get("HF_GALLERY_REPO") or DEFAULT_REPO)
    parser.add_argument("--out", default=".cache/hf-gallery")
    args = parser.parse_args(argv)
    path = pull(args.repo, Path(args.out))
    print(f"pulled {args.repo} -> {path}")


if __name__ == "__main__":
    main()
