"""Generic adapter: official ComfyUI UI JSON → API prompt → queue → download.

Per-workflow scripts should only exist when the Image is missing nodes or the
lock resolver needs a hand-curated file. Conversion itself is always the same
thing the web UI does: ``app.graphToPrompt()``.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from storage import safe_dest_file

OUTPUT_KEYS = ("images", "gifs", "videos", "audio", "3d", "mesh", "files")
TEXT_CLASS_TYPES = {
    "CLIPTextEncode",
    "CLIPTextEncodeSDXL",
    "CLIPTextEncodeFlux",
    "PrimitiveStringMultiline",
    "PrimitiveString",
}
NEGATIVE_MARKERS = ("negative", "neg", "负向", "反向")
GRAPH_TO_PROMPT_JS = """
async (workflow) => {
    const app = window.comfyAPI?.app?.app;
    if (!app) return { ok: false, error: 'comfyAPI.app.app missing' };
    const graphNodes = () => app.graph?.nodes || app.graph?._nodes || [];
    const expectedTypes = [...new Set((workflow?.nodes || []).map((node) => node.type).filter(Boolean))];
    try {
        await app.loadGraphData(workflow);
        let loadedTypes = [];
        for (let i = 0; i < 40; i++) {
            await new Promise((resolve) => setTimeout(resolve, 250));
            loadedTypes = graphNodes().map((node) => String(node.type || node.comfyClass || ''));
            const ready = expectedTypes.length > 0 && expectedTypes.every((type) => loadedTypes.includes(type));
            if (ready) break;
        }
        const converted = await app.graphToPrompt();
        const prompt = converted?.output || converted;
        const missing = [];
        for (const node of graphNodes()) {
            const type = node.type || node.comfyClass || '';
            if (String(type).toLowerCase().includes('missing')) {
                missing.push({ id: node.id, type, title: node.title });
            }
        }
        if (!prompt || typeof prompt !== 'object' || Array.isArray(prompt)) {
            return { ok: false, error: 'graphToPrompt failed', missing, loadedTypes, expectedTypes };
        }
        return {
            ok: true,
            prompt,
            missing,
            node_count: Object.keys(prompt).length,
            loaded_types: loadedTypes,
            expected_types: expectedTypes,
        };
    } catch (error) {
        return { ok: false, error: String((error && error.stack) || error) };
    }
}
"""
IDLE_REMINDER = (
    "任务已结束。scaledown 5s 挡不住 leftover modal serve / 开着的 ComfyUI。"
    "请立刻停掉 serve，不要把贵卡挂着。"
)


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
            devices = [
                device.get("name") for device in (stats.get("devices") or [])
            ]
            print(json.dumps({"ready": True, "devices": devices}), flush=True)
            return stats
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(2)
    raise TimeoutError(f"ComfyUI not ready: {last_error}")


def queue_prompt_ids(queue: Any) -> set[str]:
    """ComfyUI ``/queue`` items are ``[number, prompt_id, prompt, extra]``."""
    ids: set[str] = set()
    if not isinstance(queue, Mapping):
        return ids
    for key in ("queue_running", "queue_pending"):
        for item in queue.get(key) or ():
            if isinstance(item, list | tuple) and len(item) >= 2:
                ids.add(str(item[1]))
    return ids


def wait_history(
    base: str,
    prompt_id: str,
    timeout: int = 45 * 60,
    *,
    lost_after: int = 60,
) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_status: dict[str, Any] | None = None
    seen_in_queue = False
    missing_since: float | None = None
    root = base.rstrip("/")
    while time.time() < deadline:
        try:
            queue = http_json(f"{root}/queue", timeout=30)
            history = http_json(f"{root}/history/{prompt_id}", timeout=30)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"poll_error": str(exc)}), flush=True)
            time.sleep(2)
            continue
        if not isinstance(queue, Mapping):
            queue = {}
        if not isinstance(history, Mapping):
            history = {}
        item = history.get(prompt_id)
        in_queue = prompt_id in queue_prompt_ids(queue)
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
        if in_queue:
            seen_in_queue = True
            missing_since = None
        else:
            if missing_since is None:
                missing_since = time.time()
            elif time.time() - missing_since >= lost_after:
                if seen_in_queue:
                    raise RuntimeError(
                        f"prompt {prompt_id} left /queue without /history "
                        f"after {lost_after}s. GPU container likely recycled "
                        "(scaledown_window=5s). Re-queue and keep polling."
                    )
                raise RuntimeError(
                    f"prompt {prompt_id} never appeared in /queue or /history "
                    f"after {lost_after}s. GPU container likely recycled "
                    "(scaledown_window=5s). Re-queue and keep polling."
                )
        time.sleep(2)
    raise TimeoutError(f"prompt {prompt_id} did not finish within {timeout}s")


def is_ui_workflow(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("nodes"), list)


def is_api_prompt(payload: Any) -> bool:
    if not isinstance(payload, dict) or is_ui_workflow(payload):
        return False
    nodes = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else payload
    if not isinstance(nodes, dict) or not nodes:
        return False
    typed = [
        node.get("class_type")
        for node in nodes.values()
        if isinstance(node, dict)
    ]
    return bool(typed) and all(isinstance(name, str) and name for name in typed)


def api_nodes(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("prompt"), dict) and is_api_prompt(payload):
        return payload["prompt"]
    return payload


def _node_title(node: dict[str, Any]) -> str:
    meta = node.get("_meta")
    if isinstance(meta, dict) and meta.get("title"):
        return str(meta["title"])
    return str(node.get("title") or "")


def _is_negative_title(title: str) -> bool:
    lowered = title.lower()
    return any(marker in lowered for marker in NEGATIVE_MARKERS)


def inspect_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    """Describe bindable nodes without a running GPU."""
    if is_api_prompt(payload):
        nodes = []
        for node_id, node in api_nodes(payload).items():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type") or "")
            title = _node_title(node)
            bind = "other"
            if class_type == "LoadImage":
                bind = "image"
            elif class_type in TEXT_CLASS_TYPES:
                bind = "negative" if _is_negative_title(title) else "prompt"
            elif class_type.startswith("Save"):
                bind = "save"
            nodes.append(
                {
                    "id": str(node_id),
                    "class_type": class_type,
                    "title": title,
                    "bind": bind,
                }
            )
        return {"format": "api", "nodes": nodes}
    if not is_ui_workflow(payload):
        raise ValueError("not a ComfyUI UI workflow or API prompt")
    nodes = []
    for node in payload.get("nodes") or ():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("type") or "")
        title = str(node.get("title") or "")
        bind = "other"
        if class_type == "LoadImage":
            bind = "image"
        elif class_type in TEXT_CLASS_TYPES:
            bind = "negative" if _is_negative_title(title) else "prompt"
        elif class_type.startswith("Save"):
            bind = "save"
        nodes.append(
            {
                "id": node.get("id"),
                "class_type": class_type,
                "title": title,
                "bind": bind,
            }
        )
    return {"format": "ui", "nodes": nodes}


def chrome_search_paths() -> list[Path]:
    paths: list[Path] = []
    override = os.environ.get("COMFY_CHROME", "").strip()
    if override:
        paths.append(Path(override))
    paths.extend(
        Path(item)
        for item in (
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/Microsoft Edge",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        )
    )
    local_app = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app:
        root = Path(local_app)
        paths.append(root / "Google" / "Chrome" / "Application" / "chrome.exe")
        paths.append(root / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
        "msedge",
    ):
        found = shutil.which(name)
        if found:
            paths.append(Path(found))
    return paths


def chrome_executable() -> str | None:
    seen: set[str] = set()
    for path in chrome_search_paths():
        resolved = str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.is_file():
            return resolved
    return None


def convert_ui_workflow(base: str, workflow: dict[str, Any]) -> dict[str, Any]:
    """Flatten subgraphs the same way the ComfyUI Queue button does."""
    from playwright.sync_api import sync_playwright

    launch: dict[str, Any] = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage"],
    }
    chrome = chrome_executable()
    if chrome:
        launch["executable_path"] = chrome
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch)
        page = browser.new_page()
        page.set_default_timeout(180_000)
        page.goto(base.rstrip("/"), wait_until="domcontentloaded")
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
        result = page.evaluate(GRAPH_TO_PROMPT_JS, workflow)
        browser.close()
    if not result.get("ok"):
        raise RuntimeError(f"browser convert failed: {result}")
    print(
        json.dumps(
            {
                "converted": True,
                "node_count": result.get("node_count"),
                "missing": result.get("missing"),
                "loaded_types": result.get("loaded_types"),
            }
        ),
        flush=True,
    )
    return result["prompt"]


def to_api_prompt(base: str | None, workflow: dict[str, Any]) -> dict[str, Any]:
    if is_api_prompt(workflow):
        return api_nodes(workflow)
    if not is_ui_workflow(workflow):
        raise ValueError("workflow is neither UI JSON nor API prompt")
    if not base:
        raise ValueError("UI workflow needs --base-url so graphToPrompt can run")
    return convert_ui_workflow(base, workflow)


def upload_image(base: str, path: Path) -> str:
    filename = path.name
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    payload = path.read_bytes()
    boundary = f"----wf{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{base.rstrip('/')}/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        uploaded = json.loads(response.read().decode("utf-8"))
    name = str(uploaded.get("name") or filename)
    print(json.dumps({"uploaded": name, "source": str(path)}), flush=True)
    return name


def bind_load_image(prompt: dict[str, Any], image_name: str) -> dict[str, Any]:
    found = False
    for node in prompt.values():
        if isinstance(node, dict) and node.get("class_type") == "LoadImage":
            node.setdefault("inputs", {})["image"] = image_name
            found = True
    if not found:
        raise RuntimeError("converted prompt has no LoadImage node")
    return prompt


SAMPLER_TYPES = {"KSampler", "KSamplerAdvanced", "SamplerCustomAdvanced"}
SEED_TYPES = SAMPLER_TYPES | {"RandomNoise"}
SCHEDULER_TYPES = {"Flux2Scheduler", "Ideogram4Scheduler"}
NUMBER_KEYS = {"seed", "steps", "cfg", "denoise", "width", "height"}
SEED_INPUT_KEYS = ("seed", "noise_seed")


def bind_number_inputs(prompt: dict[str, Any], values: Mapping[str, Any]) -> dict[str, Any]:
    """Overwrite sampler / latent widgets that already exist. Do not invent nodes."""
    wanted = {
        key: values[key]
        for key in NUMBER_KEYS
        if key in values and values[key] is not None
    }
    if not wanted:
        return prompt
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        inputs = node.setdefault("inputs", {})
        class_type = str(node.get("class_type") or "")
        if class_type in SEED_TYPES and "seed" in wanted:
            for key in SEED_INPUT_KEYS:
                if key in inputs:
                    inputs[key] = wanted["seed"]
        if class_type in SAMPLER_TYPES | SCHEDULER_TYPES:
            for key in ("steps", "cfg", "denoise"):
                if key in wanted and key in inputs:
                    inputs[key] = wanted[key]
        if (
            (class_type.startswith("Empty") and "Latent" in class_type)
            or class_type in SCHEDULER_TYPES
        ):
            for key in ("width", "height"):
                if key in wanted and key in inputs:
                    inputs[key] = wanted[key]
    return prompt


def bind_filename_prefix(prompt: dict[str, Any], prefix: str) -> dict[str, Any]:
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        if not str(node.get("class_type") or "").startswith("Save"):
            continue
        inputs = node.setdefault("inputs", {})
        if "filename_prefix" in inputs:
            inputs["filename_prefix"] = prefix
    return prompt


def _text_input_key(node: dict[str, Any]) -> str:
    inputs = node.setdefault("inputs", {})
    if "text" in inputs or str(node.get("class_type") or "").startswith("CLIPText"):
        return "text"
    return "value"


def _text_is_widget(node: dict[str, Any]) -> bool:
    key = _text_input_key(node)
    return not isinstance((node.get("inputs") or {}).get(key), list)


def _prefer_text_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer the user-facing string widget, not a CLIPTextEncode fed by a link."""
    titled = [
        node
        for node in nodes
        if "user prompt" in _node_title(node).lower() and _text_is_widget(node)
    ]
    if titled:
        return titled
    widgets = [node for node in nodes if _text_is_widget(node)]
    return widgets or nodes


def bind_text_prompt(
    prompt: dict[str, Any],
    text: str | None = None,
    negative: str | None = None,
) -> dict[str, Any]:
    positives: list[dict[str, Any]] = []
    negatives: list[dict[str, Any]] = []
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") not in TEXT_CLASS_TYPES:
            continue
        bucket = negatives if _is_negative_title(_node_title(node)) else positives
        bucket.append(node)
    if text is not None:
        positives = _prefer_text_nodes(positives)
        if not positives:
            raise RuntimeError("converted prompt has no text node to bind")
        key = _text_input_key(positives[0])
        positives[0].setdefault("inputs", {})[key] = text
    if negative is not None:
        if not negatives and len(positives) > 1:
            negatives = positives[1:]
        negatives = _prefer_text_nodes(negatives)
        if not negatives:
            raise RuntimeError("converted prompt has no negative text node to bind")
        key = _text_input_key(negatives[0])
        negatives[0].setdefault("inputs", {})[key] = negative
    return prompt


def queue_prompt(base: str, prompt: dict[str, Any], client_id: str) -> str:
    queued = http_json(
        f"{base.rstrip('/')}/prompt",
        {"prompt": prompt, "client_id": client_id},
        timeout=120,
    )
    if queued.get("error") or queued.get("node_errors"):
        raise RuntimeError(json.dumps(queued, ensure_ascii=False)[:4000])
    prompt_id = queued.get("prompt_id")
    if not prompt_id:
        raise RuntimeError("ComfyUI /prompt returned no prompt_id")
    return str(prompt_id)


def download_outputs(base: str, history: dict[str, Any], dest: Path) -> list[Path]:
    saved: list[Path] = []
    dest.mkdir(parents=True, exist_ok=True)
    root = base.rstrip("/")
    for node_output in (history.get("outputs") or {}).values():
        if not isinstance(node_output, dict):
            continue
        for key in OUTPUT_KEYS:
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
                path = safe_dest_file(dest, str(item["filename"]))
                with urllib.request.urlopen(f"{root}/view?{query}", timeout=300) as response:
                    path.write_bytes(response.read())
                saved.append(path)
                print(
                    json.dumps({"saved": str(path), "bytes": path.stat().st_size}),
                    flush=True,
                )
    status = (history.get("status") or {}).get("status_str")
    if status and status != "success" and not saved:
        raise RuntimeError(f"ComfyUI history status={status!r} and no outputs")
    return saved


def run_jobs(
    *,
    base: str,
    workflow: dict[str, Any],
    out: Path,
    images: list[Path] | None = None,
    prompt: str | None = None,
    negative: str | None = None,
    client_id: str = "workflow-queue",
    ready_timeout: int = 900,
) -> list[dict[str, Any]]:
    out.mkdir(parents=True, exist_ok=True)
    stats = wait_ready(base, timeout=ready_timeout)
    template = to_api_prompt(base, workflow)
    (out / "workflow.api.json").write_text(
        json.dumps(template, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    sources = images or [None]
    records: list[dict[str, Any]] = []
    for source in sources:
        graph = json.loads(json.dumps(template))
        if source is not None:
            uploaded = upload_image(base, source)
            bind_load_image(graph, uploaded)
        if prompt is not None or negative is not None:
            bind_text_prompt(graph, text=prompt, negative=negative)
        started = time.time()
        prompt_id = queue_prompt(base, graph, client_id)
        label = source.name if source is not None else "prompt"
        print(json.dumps({"queued": prompt_id, "job": label}), flush=True)
        history = wait_history(base, prompt_id)
        status = history.get("status") or {}
        if status.get("status_str") == "error":
            raise RuntimeError(json.dumps(status, ensure_ascii=False)[:4000])
        dest = out / (source.stem if source is not None else "run")
        saved = download_outputs(base, history, dest)
        record = {
            "job": label,
            "prompt_id": prompt_id,
            "seconds": round(time.time() - started, 2),
            "files": [str(path) for path in saved],
            "gpu": ((stats.get("devices") or [{}])[0].get("name")),
            "status": status.get("status_str"),
        }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    (out / "result.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(IDLE_REMINDER, flush=True)
    return records


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Convert any ComfyUI UI workflow via graphToPrompt and queue it.",
    )
    parser.add_argument("--workflow", required=True, help="UI JSON or API prompt JSON")
    parser.add_argument("--base-url", default="", help="running ComfyUI *.modal.run")
    parser.add_argument("--images", nargs="*", default=[], help="bind LoadImage, one job each")
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--negative", default=None)
    parser.add_argument("--out", default="artifacts/workflow")
    parser.add_argument("--client-id", default="workflow-queue")
    parser.add_argument("--ready-timeout", type=int, default=900)
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="print bindable nodes; does not need a GPU",
    )
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.workflow).read_text(encoding="utf-8"))
    if args.inspect:
        print(json.dumps(inspect_workflow(payload), indent=2, ensure_ascii=False))
        return
    if not args.base_url:
        raise SystemExit("queueing needs --base-url (omit it only with --inspect)")
    run_jobs(
        base=args.base_url.rstrip("/"),
        workflow=payload,
        out=Path(args.out),
        images=[Path(item) for item in args.images],
        prompt=args.prompt,
        negative=args.negative,
        client_id=args.client_id,
        ready_timeout=args.ready_timeout,
    )


if __name__ == "__main__":
    main()
