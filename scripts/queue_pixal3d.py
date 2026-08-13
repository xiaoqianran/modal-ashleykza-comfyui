#!/usr/bin/env python3
"""Convert the Pixal3D UI workflow, queue image→GLB jobs, save outputs."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from workflow_queue import (  # noqa: E402,I001
    IDLE_REMINDER,
    bind_load_image,
    convert_ui_workflow as convert_with_browser,
    download_outputs as download_history_outputs,
    http_json as _http_json,
    upload_image,
    wait_history,
    wait_ready,
)

CLIENT_ID = "pixal3d-agent"


def _iter_glb_names(obj: Any) -> list[str]:
    names: list[str] = []
    if isinstance(obj, str) and obj.lower().endswith(".glb"):
        names.append(obj.replace("\\", "/"))
    elif isinstance(obj, dict):
        for value in obj.values():
            names.extend(_iter_glb_names(value))
    elif isinstance(obj, list):
        for item in obj:
            names.extend(_iter_glb_names(item))
    return names


def download_outputs(base: str, history: dict, dest: Path) -> list[Path]:
    saved = download_history_outputs(base, history, dest)
    seen = {path.name for path in saved}
    for raw in _iter_glb_names(history):
        name = Path(raw).name
        if name in seen:
            continue
        query = urllib.parse.urlencode(
            {"filename": name, "subfolder": "", "type": "output"}
        )
        path = dest / name
        dest.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{base}/view?{query}", timeout=300) as response:
            path.write_bytes(response.read())
        saved.append(path)
        seen.add(name)
        print(json.dumps({"saved": str(path), "bytes": path.stat().st_size}), flush=True)
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--workflow", default="examples/pixal3d-image-to-3d.json")
    parser.add_argument("--images", nargs="+", required=True)
    parser.add_argument("--out", default="artifacts/pixal3d")
    parser.add_argument("--ready-timeout", type=int, default=3600)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    workflow = json.loads(Path(args.workflow).read_text(encoding="utf-8"))
    stats = wait_ready(base, timeout=args.ready_timeout)
    prompt_template = convert_with_browser(base, workflow)
    (out / "pixal3d.api.json").write_text(
        json.dumps(prompt_template, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    records = []
    for image_path in args.images:
        path = Path(image_path)
        uploaded = upload_image(base, path)
        prompt = json.loads(json.dumps(prompt_template))
        bind_load_image(prompt, uploaded)
        started = time.time()
        queued = _http_json(
            f"{base}/prompt",
            {"prompt": prompt, "client_id": CLIENT_ID},
            timeout=120,
        )
        if queued.get("error") or queued.get("node_errors"):
            raise RuntimeError(json.dumps(queued, ensure_ascii=False)[:4000])
        prompt_id = queued["prompt_id"]
        print(json.dumps({"queued": prompt_id, "image": path.name}), flush=True)
        history = wait_history(base, prompt_id)
        status = history.get("status") or {}
        if status.get("status_str") == "error" or not status.get("completed", True):
            raise RuntimeError(json.dumps(status, ensure_ascii=False)[:4000])
        dest = out / path.stem
        saved = download_outputs(base, history, dest)
        record = {
            "image": path.name,
            "prompt_id": prompt_id,
            "seconds": round(time.time() - started, 2),
            "files": [str(item) for item in saved],
            "gpu": ((stats.get("devices") or [{}])[0].get("name")),
            "status": status.get("status_str"),
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    (out / "result.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(IDLE_REMINDER, flush=True)


if __name__ == "__main__":
    main()
