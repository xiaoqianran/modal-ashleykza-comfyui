#!/usr/bin/env python3
"""Queue the campus-days storyboard against a running FLUX.2 ComfyUI and save PNGs."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflow_queue import wait_history

STORYBOARD = ROOT / "examples" / "campus-days-storyboard.json"


def _load_api_template(base: str) -> dict:
    import workflow_queue
    from catalog import load_catalog, workflow_path

    catalog = load_catalog("flux2-dev")
    workflow = json.loads(workflow_path(catalog).read_text(encoding="utf-8"))
    return workflow_queue.to_api_prompt(base, workflow)


def _prompt_graph(template: dict, positive: str, seed: int) -> dict:
    from catalog import build_prompt, load_catalog

    graph, _values = build_prompt(
        load_catalog("flux2-dev"),
        {
            "prompt": positive,
            "seed": seed,
            "filename_prefix": "Campus_days",
        },
        api_prompt=template,
    )
    return graph


def _http_json(url: str, payload: dict | None = None, timeout: int = 60) -> dict | list:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="GET" if data is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode())


def wait_ready(base: str, timeout: int = 1800) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base}/system_stats", timeout=10)
            return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(5)
    raise TimeoutError(f"ComfyUI at {base} did not become ready within {timeout}s")


def _safe_dest(dest: Path, filename: str) -> Path:
    dest = dest.resolve()
    name = Path(str(filename).replace("\\", "/")).name
    if not name or name in {".", ".."}:
        raise ValueError(f"unsafe output filename: {filename!r}")
    path = (dest / name).resolve()
    if path != dest and dest not in path.parents:
        raise ValueError(f"output path escapes destination: {filename!r}")
    return path


def download_images(base: str, history: dict, dest: Path) -> list[Path]:
    saved: list[Path] = []
    dest.mkdir(parents=True, exist_ok=True)
    status = (history.get("status") or {}).get("status_str")
    if status and status != "success":
        raise RuntimeError(f"ComfyUI history status={status!r}")
    for node_output in history.get("outputs", {}).values():
        for image in node_output.get("images", []):
            query = urllib.parse.urlencode(
                {
                    "filename": image["filename"],
                    "subfolder": image.get("subfolder") or "",
                    "type": image.get("type") or "output",
                }
            )
            url = f"{base}/view?{query}"
            path = _safe_dest(dest, str(image["filename"]))
            with urllib.request.urlopen(url, timeout=120) as response:
                path.write_bytes(response.read())
            saved.append(path)
    return saved


def load_storyboard(path: Path = STORYBOARD) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    frames = data.get("frames") or []
    if not frames:
        raise ValueError(f"no frames in {path}")
    return data


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run FLUX.2 campus storyboard batch.")
    parser.add_argument("--base-url", help="Running modal serve ComfyUI base URL")
    parser.add_argument("--out", default="artifacts/campus-days-flux2")
    parser.add_argument("--storyboard", default=str(STORYBOARD))
    parser.add_argument("--start", type=int, default=1, help="1-based frame index to start")
    parser.add_argument("--end", type=int, default=0, help="1-based inclusive end; 0 = all")
    parser.add_argument("--dry-run", action="store_true", help="Print selected frames only")
    args = parser.parse_args()

    data = load_storyboard(Path(args.storyboard))
    frames = data["frames"]
    start = max(1, args.start)
    end = args.end if args.end > 0 else len(frames)
    selected = frames[start - 1 : end]
    if not selected:
        raise SystemExit(f"no frames in range {start}-{end}")

    if args.dry_run:
        for frame in selected:
            print(json.dumps(frame, ensure_ascii=False), flush=True)
        return

    if not args.base_url:
        raise SystemExit("--base-url is required unless --dry-run is set")

    base = args.base_url.rstrip("/")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    timings = []
    wait_ready(base)
    template = _load_api_template(base)
    (out / "workflow.api.json").write_text(
        json.dumps(template, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for offset, frame in enumerate(selected, start=start):
        started = time.time()
        payload = {
            "prompt": _prompt_graph(template, frame["text"], seed=2000 + offset * 13),
            "client_id": "flux2-campus-storyboard",
        }
        queued = _http_json(f"{base}/prompt", payload)
        if queued.get("error") or queued.get("node_errors"):
            raise RuntimeError(json.dumps(queued, ensure_ascii=False)[:4000])
        prompt_id = queued["prompt_id"]
        history = wait_history(base, prompt_id)
        images = download_images(base, history, out)
        if not images:
            raise RuntimeError(f"frame {frame['id']} finished without images")
        elapsed = time.time() - started
        record = {
            "id": frame["id"],
            "title": frame.get("title"),
            "act": frame.get("act"),
            "prompt": frame["text"],
            "prompt_id": prompt_id,
            "seconds": round(elapsed, 2),
            "images": [str(path) for path in images],
        }
        timings.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)

    meta = {
        "storyboard": data.get("title"),
        "flux2_notes": data.get("flux2_notes"),
        "range": [start, end],
        "frames": timings,
    }
    (out / "timings.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    from modal_config import GPU_IDLE_REMINDER

    print(GPU_IDLE_REMINDER, flush=True)


if __name__ == "__main__":
    main()
