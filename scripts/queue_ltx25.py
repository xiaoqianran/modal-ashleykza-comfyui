#!/usr/bin/env python3
"""Patch the LTX-2.5 UI workflow for ComfyUI 0.32.0, convert, queue, save video."""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import urllib.request
import uuid
import zlib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from workflow_queue import (  # noqa: E402
    IDLE_REMINDER,
    download_outputs,
    iter_node_lists,
    queue_prompt,
    wait_history,
    wait_ready,
)
from workflow_queue import convert_ui_workflow as convert_with_browser  # noqa: E402

CLIENT_ID = "ltx25-agent"
MISSING_API_TYPES = {"GemmaAPITextEncode"}
FLOAT_TO_INT_TYPE = "LTXFloatToInt"


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
    wait_ready(base, workflow=patched)
    prompt = convert_with_browser(base, patched)
    dummy = upload_dummy_image(base)
    prompt = fix_converted_prompt(prompt, dummy)
    api_path = out / "ltx25.api.json"
    api_path.write_text(json.dumps(prompt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    started = time.time()
    prompt_id = queue_prompt(base, prompt, CLIENT_ID)
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
    print(IDLE_REMINDER, flush=True)


if __name__ == "__main__":
    main()
