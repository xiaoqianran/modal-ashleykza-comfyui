"""Talk to a running ComfyUI HTTP API."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def http_json(url: str, payload: dict | None = None, timeout: int = 120) -> Any:
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


def wait_ready(base: str, timeout: int = 900) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            stats = http_json(f"{base.rstrip('/')}/system_stats", timeout=20)
            devices = stats.get("devices") or []
            return {
                "ready": True,
                "devices": [device.get("name") for device in devices],
            }
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(2)
    raise TimeoutError(f"ComfyUI not ready: {last_error}")


def wait_history(base: str, prompt_id: str, timeout: int = 900) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        history = http_json(f"{base.rstrip('/')}/history/{prompt_id}", timeout=30)
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(2)
    raise TimeoutError(f"prompt {prompt_id} did not finish within {timeout}s")


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


def queue_prompt(base: str, graph: dict[str, Any], client_id: str) -> str:
    queued = http_json(
        f"{base.rstrip('/')}/prompt",
        {"prompt": graph, "client_id": client_id},
        timeout=120,
    )
    if queued.get("error") or queued.get("node_errors"):
        raise RuntimeError(json.dumps(queued, ensure_ascii=False)[:4000])
    prompt_id = queued.get("prompt_id")
    if not prompt_id:
        raise RuntimeError("ComfyUI /prompt returned no prompt_id")
    return str(prompt_id)
