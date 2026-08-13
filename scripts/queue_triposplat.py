#!/usr/bin/env python3
"""Convert the TripoSplat UI workflow, queue N image→splat jobs, save outputs."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from workflow_queue import (  # noqa: E402,I001
    convert_ui_workflow as convert_with_browser,
    wait_history,
)

CLIENT_ID = "triposplat-agent"
ENABLE_GLB_TYPES = {"SplatToMesh", "SaveGLB"}


def _http_json(url: str, payload: dict | None = None, timeout: int = 120) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="GET" if data is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return json.loads(body.decode("utf-8") or "{}")


def wait_ready(base: str, timeout: int = 300) -> dict:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            stats = _http_json(f"{base}/system_stats", timeout=30)
            devices = stats.get("devices") or []
            print(json.dumps({"ready": True, "devices": [d.get("name") for d in devices]}), flush=True)
            return stats
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"ComfyUI not ready: {last_error}")


def iter_node_lists(obj: Any):
    if isinstance(obj, dict):
        nodes = obj.get("nodes")
        if isinstance(nodes, list) and nodes and isinstance(nodes[0], dict) and "type" in nodes[0]:
            yield obj, nodes
        for value in obj.values():
            yield from iter_node_lists(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_node_lists(item)


def enable_glb_export(workflow: dict) -> dict:
    """Official template bypasses mesh/GLB export; turn those nodes back on."""
    for _container, nodes in iter_node_lists(workflow):
        for node in nodes:
            if isinstance(node, dict) and node.get("type") in ENABLE_GLB_TYPES:
                node["mode"] = 0
    return workflow


def upload_image(base: str, path: Path) -> str:
    filename = path.name
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    payload = path.read_bytes()
    boundary = f"----tripo{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{base}/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        uploaded = json.loads(response.read().decode("utf-8"))
    name = str(uploaded.get("name") or filename)
    print(json.dumps({"uploaded": name, "source": str(path)}), flush=True)
    return name


def bind_load_image(prompt: dict, image_name: str) -> dict:
    found = False
    for node in prompt.values():
        if isinstance(node, dict) and node.get("class_type") == "LoadImage":
            node.setdefault("inputs", {})["image"] = image_name
            found = True
    if not found:
        raise RuntimeError("converted prompt has no LoadImage node")
    return prompt


def _safe_dest(dest: Path, filename: str) -> Path:
    dest = dest.resolve()
    name = Path(str(filename).replace("\\", "/")).name
    if not name or name in {".", ".."}:
        raise ValueError(f"unsafe output filename: {filename!r}")
    path = (dest / name).resolve()
    if path != dest and dest not in path.parents:
        raise ValueError(f"output path escapes destination: {filename!r}")
    return path


def download_outputs(base: str, history: dict, dest: Path) -> list[Path]:
    saved: list[Path] = []
    dest.mkdir(parents=True, exist_ok=True)
    for node_output in (history.get("outputs") or {}).values():
        if not isinstance(node_output, dict):
            continue
        for key in ("images", "gifs", "videos", "audio", "3d", "mesh", "files"):
            for item in node_output.get(key) or []:
                if isinstance(item, str):
                    item = {"filename": item}
                if not isinstance(item, dict) or not item.get("filename"):
                    continue
                query = urllib.parse.urlencode(
                    {
                        "filename": item["filename"],
                        "subfolder": item.get("subfolder") or "",
                        "type": item.get("type") or "output",
                    }
                )
                path = _safe_dest(dest, str(item["filename"]))
                with urllib.request.urlopen(f"{base}/view?{query}", timeout=300) as response:
                    path.write_bytes(response.read())
                saved.append(path)
                print(json.dumps({"saved": str(path), "bytes": path.stat().st_size}), flush=True)
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--workflow",
        default="examples/triposplat-image-to-gaussian-splat.json",
    )
    parser.add_argument("--images", nargs="+", required=True)
    parser.add_argument("--out", default="artifacts/triposplat")
    parser.add_argument("--enable-glb", action="store_true", default=True)
    parser.add_argument("--no-glb", action="store_true")
    parser.add_argument("--ready-timeout", type=int, default=900)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    workflow = json.loads(Path(args.workflow).read_text(encoding="utf-8"))
    if args.enable_glb and not args.no_glb:
        enable_glb_export(workflow)
    stats = wait_ready(base, timeout=args.ready_timeout)
    prompt_template = convert_with_browser(base, workflow)
    (out / "triposplat.api.json").write_text(
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
    print(
        "任务已结束。scaledown 5s 挡不住 leftover modal serve / 开着的 ComfyUI。"
        "请立刻停掉 serve，不要把贵卡挂着。",
        flush=True,
    )


if __name__ == "__main__":
    main()
