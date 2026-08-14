"""Talk to a running ComfyUI HTTP API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import workflow_queue


def http_json(url: str, payload: dict | None = None, timeout: int = 120) -> Any:
    return workflow_queue.http_json(url, payload, timeout=timeout)


def wait_ready(base: str, timeout: int = 900) -> dict[str, Any]:
    stats = workflow_queue.wait_ready(base, timeout=timeout)
    devices = stats.get("devices") or []
    return {
        "ready": True,
        "devices": [device.get("name") for device in devices],
    }


def wait_history(base: str, prompt_id: str, timeout: int = 900) -> dict[str, Any]:
    return workflow_queue.wait_history(base, prompt_id, timeout=timeout)


def queue_prompt(base: str, graph: dict[str, Any], client_id: str) -> str:
    return workflow_queue.queue_prompt(base, graph, client_id)


def download_images(base: str, history: dict[str, Any], dest: Path) -> list[Path]:
    """Backward-compatible alias. Prefer ``workflow_queue.download_outputs``."""
    return workflow_queue.download_outputs(base, history, dest)
