#!/usr/bin/env python3
"""Queue five Z-Image prompts against a running ComfyUI and save PNGs."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

PROMPTS = [
    {
        "id": "01-blue-forest-fashion",
        "text": (
            "A fashion photography work full of surreal romanticism, low-angle upward shot, "
            "clear ice-blue sky, fantasy cobalt vegetation and an African-American model in a "
            "yellow-and-white vertical striped long dress walking on warm sand. Delicate leaf "
            "textures, noon sun, sharp shadows, quiet high-fashion poetic atmosphere, "
            "photorealistic, 85mm, editorial lighting."
        ),
    },
    {
        "id": "02-shanghai-rain-night",
        "text": (
            "Cinematic night portrait on a rain-soaked Shanghai side street, neon reflections "
            "on wet asphalt, a young woman in a charcoal trench coat under a transparent umbrella, "
            "steam from a roadside noodle stall, teal and amber color grade, shallow depth of field, "
            "35mm still, photorealistic."
        ),
    },
    {
        "id": "03-porcelain-still-life",
        "text": (
            "Studio still life of a celadon porcelain tea set on dark walnut, a single shaft of "
            "window light, drifting tea steam, tiny water beads on the glaze, museum catalog "
            "composition, ultra-detailed ceramic texture, photorealistic."
        ),
    },
    {
        "id": "04-karst-fog-aerial",
        "text": (
            "Aerial cinematic view of limestone karst peaks rising through morning fog, a narrow "
            "river like a silver thread, distant terraced fields, cool mist and warm sunrise rim "
            "light, large-format landscape photography, photorealistic."
        ),
    },
    {
        "id": "05-workshop-craftsman",
        "text": (
            "Portrait of an elderly wood craftsman in a sunlit workshop, sawdust in volumetric "
            "light, worn hands holding a carving chisel, rows of tools on a pegboard, earthy "
            "palette, documentary photography, 50mm, photorealistic."
        ),
    },
]


def _prompt_graph(positive: str, seed: int) -> dict:
    return {
        "62": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen_3_4b.safetensors",
                "type": "lumina2",
                "device": "default",
            },
        },
        "63": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "ae.safetensors"},
        },
        "66": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "z_image_bf16.safetensors",
                "weight_dtype": "default",
            },
        },
        "70": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["66", 0], "shift": 3.0},
        },
        "67": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["62", 0], "text": positive},
        },
        "71": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["62", 0], "text": ""},
        },
        "68": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
        },
        "69": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["70", 0],
                "positive": ["67", 0],
                "negative": ["71", 0],
                "latent_image": ["68", 0],
                "seed": seed,
                "steps": 25,
                "cfg": 4.0,
                "sampler_name": "res_multistep",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "65": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["69", 0], "vae": ["63", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["65", 0],
                "filename_prefix": "Z_image_base",
            },
        },
    }


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


def wait_ready(base: str, timeout: int = 900) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base}/system_stats", timeout=10)
            return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(5)
    raise TimeoutError(f"ComfyUI at {base} did not become ready within {timeout}s")


def wait_history(base: str, prompt_id: str, timeout: int = 900) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        history = _http_json(f"{base}/history/{prompt_id}")
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(2)
    raise TimeoutError(f"prompt {prompt_id} did not finish within {timeout}s")


def download_images(base: str, history: dict, dest: Path) -> list[Path]:
    saved: list[Path] = []
    for node_output in history.get("outputs", {}).values():
        for image in node_output.get("images", []):
            query = (
                f"filename={image['filename']}&subfolder={image.get('subfolder', '')}"
                f"&type={image.get('type', 'output')}"
            )
            url = f"{base}/view?{query}"
            path = dest / image["filename"]
            with urllib.request.urlopen(url, timeout=120) as response:
                path.write_bytes(response.read())
            saved.append(path)
    return saved


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--out", default="/opt/cursor/artifacts/z-image-runs")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    timings = []
    wait_ready(base)
    for index, item in enumerate(PROMPTS, start=1):
        started = time.time()
        payload = {
            "prompt": _prompt_graph(item["text"], seed=1000 + index * 17),
            "client_id": "z-image-agent",
        }
        queued = _http_json(f"{base}/prompt", payload)
        prompt_id = queued["prompt_id"]
        history = wait_history(base, prompt_id)
        images = download_images(base, history, out)
        elapsed = time.time() - started
        record = {
            "id": item["id"],
            "prompt": item["text"],
            "prompt_id": prompt_id,
            "seconds": round(elapsed, 2),
            "images": [str(path) for path in images],
        }
        timings.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)

    (out / "timings.json").write_text(
        json.dumps(timings, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
