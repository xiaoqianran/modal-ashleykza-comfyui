"""Talk to a running ComfyUI HTTP API."""

from __future__ import annotations

import urllib.parse
import urllib.request
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


def _safe_dest(dest: Path, filename: str) -> Path:
    dest = dest.resolve()
    name = Path(str(filename).replace("\\", "/")).name
    if not name or name in {".", ".."}:
        raise ValueError(f"unsafe output filename: {filename!r}")
    path = (dest / name).resolve()
    if path != dest and dest not in path.parents:
        raise ValueError(f"output path escapes destination: {filename!r}")
    return path


def download_images(base: str, history: dict[str, Any], dest: Path) -> list[Path]:
    saved: list[Path] = []
    dest.mkdir(parents=True, exist_ok=True)
    status = (history.get("status") or {}).get("status_str")
    if status and status != "success":
        raise RuntimeError(f"ComfyUI history status={status!r}")
    for node_output in (history.get("outputs") or {}).values():
        for image in node_output.get("images") or ():
            query = urllib.parse.urlencode(
                {
                    "filename": image["filename"],
                    "subfolder": image.get("subfolder") or "",
                    "type": image.get("type") or "output",
                }
            )
            url = f"{base.rstrip('/')}/view?{query}"
            path = _safe_dest(dest, str(image["filename"]))
            with urllib.request.urlopen(url, timeout=120) as response:
                path.write_bytes(response.read())
            saved.append(path)
    return saved
