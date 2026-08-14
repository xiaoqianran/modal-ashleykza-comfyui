#!/usr/bin/env python3
"""Queue five Z-Image prompts against a running ComfyUI and save PNGs."""

from __future__ import annotations

import json
import time
from pathlib import Path

from workflow_queue import IDLE_REMINDER, download_outputs, queue_prompt, wait_history
from workflow_queue import wait_ready as wait_comfy_ready

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
    from catalog import bind_graph, load_catalog

    graph, _values = bind_graph(
        load_catalog("z-image"),
        {
            "prompt": positive,
            "seed": seed,
            "filename_prefix": "Z_image_base",
        },
    )
    return graph


def wait_ready(base: str, timeout: int = 900) -> None:
    from catalog import load_catalog

    wait_comfy_ready(
        base,
        timeout=timeout,
        workflow=load_catalog("z-image").get("graph"),
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--out", default="artifacts/z-image-runs")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    timings = []
    wait_ready(base)
    for index, item in enumerate(PROMPTS, start=1):
        started = time.time()
        prompt_id = queue_prompt(
            base,
            _prompt_graph(item["text"], seed=1000 + index * 17),
            "z-image-agent",
        )
        history = wait_history(base, prompt_id)
        images = download_outputs(base, history, out)
        if not images:
            raise RuntimeError(f"prompt {prompt_id} finished without images")
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
    print(IDLE_REMINDER, flush=True)


if __name__ == "__main__":
    main()
