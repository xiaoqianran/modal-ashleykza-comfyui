#!/usr/bin/env python3
"""Patch the LTX-2.5 UI workflow for ComfyUI 0.32.0, convert, queue, save video."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
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
            """() => Boolean(
                window.app?.loadGraphData
                || window.app?.graph
                || document.querySelector('canvas')
            )""",
            timeout=180_000,
        )
        # Give node defs / subgraph registry time to finish loading.
        page.wait_for_timeout(4000)
        result = page.evaluate(
            """async (workflow) => {
                const app = window.app;
                if (!app) return { ok: false, error: 'window.app missing' };
                if (typeof app.loadGraphData === 'function') {
                    await app.loadGraphData(workflow);
                } else {
                    return { ok: false, error: 'loadGraphData missing' };
                }
                await new Promise((resolve) => setTimeout(resolve, 1500));
                let prompt = null;
                if (typeof app.graphToPrompt === 'function') {
                    const converted = await app.graphToPrompt();
                    prompt = converted?.output || converted;
                }
                const missing = [];
                const graph = app.graph;
                const nodes = graph?.nodes || graph?._nodes || [];
                for (const node of nodes) {
                    const type = node.type || node.comfyClass || '';
                    if (String(type).toLowerCase().includes('missing')) {
                        missing.push({ id: node.id, type, title: node.title });
                    }
                }
                if (!prompt || typeof prompt !== 'object') {
                    return { ok: false, error: 'graphToPrompt failed', missing };
                }
                return { ok: true, prompt, missing, node_count: Object.keys(prompt).length };
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
                query = (
                    f"filename={item['filename']}&subfolder={item.get('subfolder', '')}"
                    f"&type={item.get('type', 'output')}"
                )
                path = dest / item["filename"]
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
    parser.add_argument("--out", default="/opt/cursor/artifacts/ltx25")
    parser.add_argument("--patched-out", default="")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    workflow_path = Path(args.workflow)
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    patched = patch_workflow(workflow)
    patched_path = Path(args.patched_out) if args.patched_out else workflow_path.with_suffix(".compat.json")
    patched_path.write_text(json.dumps(patched, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"patched": str(patched_path)}), flush=True)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    wait_ready(base)
    prompt = convert_with_browser(base, patched)
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
