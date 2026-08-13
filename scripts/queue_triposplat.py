#!/usr/bin/env python3
"""Convert the TripoSplat UI workflow, queue N image→splat jobs, save outputs."""

from __future__ import annotations

import argparse
import json
import mimetypes
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

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


def convert_with_browser(base: str, workflow: dict) -> dict:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page()
        page.set_default_timeout(180_000)
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_function(
            """() => {
                const app = window.comfyAPI?.app?.app;
                return Boolean(
                    app?.vueAppReady
                    && app?.canvas
                    && (app.graph || app.rootGraphInternal)
                    && typeof app.loadGraphData === 'function'
                );
            }""",
            timeout=180_000,
        )
        page.wait_for_timeout(1000)
        result = page.evaluate(
            """async (workflow) => {
                const app = window.comfyAPI?.app?.app;
                if (!app) return { ok: false, error: 'comfyAPI.app.app missing' };
                try {
                    await app.loadGraphData(workflow);
                    await new Promise((resolve) => setTimeout(resolve, 1500));
                    const converted = await app.graphToPrompt();
                    const prompt = converted?.output || converted;
                    const missing = [];
                    const nodes = app.graph?.nodes || app.graph?._nodes || [];
                    for (const node of nodes) {
                        const type = node.type || node.comfyClass || '';
                        if (String(type).toLowerCase().includes('missing')) {
                            missing.push({ id: node.id, type, title: node.title });
                        }
                    }
                    if (!prompt || typeof prompt !== 'object' || Array.isArray(prompt)) {
                        return { ok: false, error: 'graphToPrompt failed', missing };
                    }
                    return {
                        ok: true,
                        prompt,
                        missing,
                        node_count: Object.keys(prompt).length,
                    };
                } catch (error) {
                    return { ok: false, error: String((error && error.stack) || error) };
                }
            }""",
            workflow,
        )
        browser.close()
    if not result.get("ok"):
        raise RuntimeError(f"browser convert failed: {result}")
    print(
        json.dumps(
            {
                "converted": True,
                "node_count": result.get("node_count"),
                "missing": result.get("missing"),
            }
        ),
        flush=True,
    )
    return result["prompt"]


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


def wait_history(base: str, prompt_id: str, timeout: int = 45 * 60) -> dict:
    deadline = time.time() + timeout
    last_status = None
    while time.time() < deadline:
        try:
            queue = _http_json(f"{base}/queue", timeout=30)
            history = _http_json(f"{base}/history/{prompt_id}", timeout=30)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"poll_error": str(exc)}), flush=True)
            time.sleep(2)
            continue
        item = history.get(prompt_id)
        status = {
            "running": len(queue.get("queue_running") or []),
            "pending": len(queue.get("queue_pending") or []),
            "done": bool(item),
        }
        if status != last_status:
            print(json.dumps({"queue": status}), flush=True)
            last_status = status
        if item:
            return item
        time.sleep(2)
    raise TimeoutError(f"prompt {prompt_id} did not finish")


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
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    workflow = json.loads(Path(args.workflow).read_text(encoding="utf-8"))
    if args.enable_glb and not args.no_glb:
        enable_glb_export(workflow)
    stats = wait_ready(base)
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


if __name__ == "__main__":
    main()
