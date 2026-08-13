#!/usr/bin/env python3
"""Patch the LTX-2.5 UI workflow for ComfyUI 0.32.0, convert, queue, save video."""

from __future__ import annotations

import argparse
import json
import struct
import time
import urllib.parse
import urllib.request
import uuid
import zlib
from pathlib import Path
from typing import Any

CLIENT_ID = "ltx25-agent"
MISSING_API_TYPES = {"GemmaAPITextEncode"}
FLOAT_TO_INT_TYPE = "LTXFloatToInt"


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


def wait_ready(base: str, timeout: int = 300) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            stats = _http_json(f"{base}/system_stats", timeout=30)
            devices = stats.get("devices") or []
            print(json.dumps({"ready": True, "devices": [d.get("name") for d in devices]}), flush=True)
            return
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


def patch_workflow(workflow: dict) -> dict:
    """Make the official LTX-2.5 subgraph workflow runnable on ComfyUI 0.32.0.

    0.32.0 has the LTX-2.5 core nodes but not GemmaAPITextEncode (API-key path)
    or LTXFloatToInt. Local T2V does not need the API encoder.
    """
    for container, nodes in iter_node_lists(workflow):
        by_id = {node.get("id"): node for node in nodes if isinstance(node, dict)}
        links = container.get("links")
        if not isinstance(links, list):
            continue

        gemma_ids = {
            node.get("id")
            for node in nodes
            if isinstance(node, dict) and node.get("type") in MISSING_API_TYPES
        }
        local_by_switch: dict[int, int] = {}
        for link in links:
            if not isinstance(link, dict):
                continue
            if link.get("origin_id") in gemma_ids:
                continue
            if link.get("type") != "CONDITIONING":
                continue
            target = by_id.get(link.get("target_id"))
            if not target or target.get("type") != "ComfySwitchNode":
                continue
            # on_false is slot 0
            if link.get("target_slot") == 0:
                local_by_switch[link["target_id"]] = link["id"]

        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("type") in MISSING_API_TYPES:
                node["mode"] = 2  # NEVER / muted
                node["type"] = "CLIPTextEncode"
                node["inputs"] = [
                    {"name": "clip", "type": "CLIP", "link": None},
                    {"name": "text", "type": "STRING", "widget": {"name": "text"}, "link": None},
                ]
                node["widgets_values"] = [""]
            elif node.get("type") == FLOAT_TO_INT_TYPE:
                node["type"] = "ComfyNumberConvert"
                for slot in node.get("inputs") or []:
                    if slot.get("name") == "a":
                        slot["name"] = "value"
                        slot.pop("label", None)
                        widget = slot.get("widget")
                        if isinstance(widget, dict):
                            widget["name"] = "value"
                # FLOAT is slot 0, INT is slot 1 on ComfyNumberConvert.
                node["outputs"] = [
                    {"name": "FLOAT", "type": "FLOAT", "links": []},
                    {
                        "name": "INT",
                        "type": "INT",
                        "links": list((node.get("outputs") or [{}])[0].get("links") or []),
                    },
                ]
                node_id = node.get("id")
                for link in links:
                    if isinstance(link, dict) and link.get("origin_id") == node_id:
                        link["origin_slot"] = 1

        for link in links:
            if not isinstance(link, dict):
                continue
            if link.get("origin_id") not in gemma_ids:
                continue
            switch_id = link.get("target_id")
            local_link_id = local_by_switch.get(switch_id)
            local = next((item for item in links if isinstance(item, dict) and item.get("id") == local_link_id), None)
            if local is None:
                continue
            link["origin_id"] = local["origin_id"]
            link["origin_slot"] = local["origin_slot"]

        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "UNETLoader":
                values = node.get("widgets_values")
                if isinstance(values, list) and values and "dev-transformer" in str(values[0]):
                    values[0] = "ltx-2.5-22b-distilled-transformer-bf16.safetensors"
            if node.get("type") == "CLIPLoader":
                values = node.get("widgets_values")
                title = str(node.get("title") or "")
                if isinstance(values, list) and values and values[0] == "ViT-B-32.pt":
                    if "Enhancer" in title:
                        values[0] = "gemma4_e2b_it_bf16.safetensors"
                    else:
                        values[0] = "gemma4-12b-with-proj-ltx-2.5-bf16.safetensors"
                    if len(values) < 2:
                        values.append("ltxv")
                    else:
                        values[1] = "ltxv"
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


def upload_dummy_image(base: str) -> str:
    """T2V still instantiates LoadImage; an empty filename fails validation."""
    width, height = 64, 64
    raw = b"".join(b"\x00" + bytes((32, 32, 40)) * width for _ in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    filename = "ltx_dummy.png"
    boundary = f"----ltx{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + png + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{base}/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        uploaded = json.loads(response.read().decode("utf-8"))
    print(json.dumps({"uploaded": uploaded}), flush=True)
    return str(uploaded.get("name") or filename)


def fix_converted_prompt(prompt: dict, dummy_image: str) -> dict:
    """Correct subgraph widget slots that 0.32.0's graphToPrompt misassigns.

    Preprocess subgraph 5514 promotes width/height/compression/strength, but the
    flattened API graph swapped them onto the wrong inner nodes.
    """
    load = prompt.get("2004")
    if isinstance(load, dict) and load.get("class_type") == "LoadImage":
        load.setdefault("inputs", {})["image"] = dummy_image
    preprocess = prompt.get("5514:3336")
    if isinstance(preprocess, dict) and preprocess.get("class_type") == "LTXVPreprocess":
        preprocess.setdefault("inputs", {})["img_compression"] = 18
    empty = prompt.get("5514:3059")
    if isinstance(empty, dict) and empty.get("class_type") == "EmptyLTXVLatentVideo":
        empty.setdefault("inputs", {})["width"] = 960
        empty["inputs"]["height"] = 544
        empty["inputs"]["batch_size"] = 1
    i2v = prompt.get("5514:3159")
    if isinstance(i2v, dict) and i2v.get("class_type") == "LTXVImgToVideoInplace":
        i2v.setdefault("inputs", {})["strength"] = 0.7
    return prompt


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
        running = (queue.get("queue_running") or []) + (queue.get("queue_pending") or [])
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
        if not running:
            # Prompt may have failed without history yet.
            time.sleep(2)
            history = _http_json(f"{base}/history/{prompt_id}", timeout=30)
            if prompt_id in history:
                return history[prompt_id]
        time.sleep(2)
    raise TimeoutError(f"prompt {prompt_id} did not finish")


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
        for key in ("images", "gifs", "videos", "audio"):
            for item in node_output.get(key) or []:
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
        default="examples/ltx-2.5-t2v-i2v-distilled.json",
    )
    parser.add_argument("--out", default="artifacts/ltx25")
    parser.add_argument("--patched-out", default="")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    workflow_path = Path(args.workflow)
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    patched = patch_workflow(workflow)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    patched_path = Path(args.patched_out) if args.patched_out else out / "ltx25.compat.json"
    patched_path.write_text(json.dumps(patched, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"patched": str(patched_path)}), flush=True)
    wait_ready(base)
    prompt = convert_with_browser(base, patched)
    dummy = upload_dummy_image(base)
    prompt = fix_converted_prompt(prompt, dummy)
    api_path = out / "ltx25.api.json"
    api_path.write_text(json.dumps(prompt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    started = time.time()
    queued = _http_json(
        f"{base}/prompt",
        {"prompt": prompt, "client_id": CLIENT_ID},
        timeout=120,
    )
    if queued.get("error") or queued.get("node_errors"):
        raise RuntimeError(json.dumps(queued, ensure_ascii=False)[:4000])
    prompt_id = queued["prompt_id"]
    print(json.dumps({"queued": prompt_id}), flush=True)
    history = wait_history(base, prompt_id)
    status = history.get("status") or {}
    if status.get("status_str") == "error" or not status.get("completed", True):
        raise RuntimeError(json.dumps(status, ensure_ascii=False)[:4000])
    saved = download_outputs(base, history, Path(args.out))
    record = {
        "prompt_id": prompt_id,
        "seconds": round(time.time() - started, 2),
        "files": [str(path) for path in saved],
        "status": status,
    }
    (Path(args.out) / "result.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
