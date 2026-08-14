"""Generic adapter: official ComfyUI UI JSON → API prompt → queue → download.

Per-workflow scripts are gated in ``catalog.gates.ALLOWED_QUEUE_SCRIPTS``.
Growing TEXT_CLASS_TYPES / SCHEDULER_TYPES / SIZE_CLASS_TYPES here is an
exception for a new node class, not a reason to add ``queue_*.py``.
Conversion itself is always the same thing the web UI does: ``app.graphToPrompt()``.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from storage import safe_dest_file

OUTPUT_KEYS = ("images", "gifs", "videos", "audio", "3d", "mesh", "files", "result")
MESH_SUFFIXES = frozenset({".glb", ".gltf", ".spz", ".splat", ".ply", ".obj"})
TEXT_CLASS_TYPES = {
    "CLIPTextEncode",
    "CLIPTextEncodeSDXL",
    "CLIPTextEncodeFlux",
    "Cosmos3TextEncode",
    "PrimitiveStringMultiline",
    "PrimitiveString",
}
NEGATIVE_MARKERS = ("negative", "neg", "负向", "反向")
ENABLE_GLB_TYPES = {"SplatToMesh", "SaveGLB"}
SKIP_OBJECT_INFO_TYPES = {
    "Note",
    "MarkdownNote",
    "Reroute",
    "GetNode",
    "SetNode",
    "Graph",
}
SUBGRAPH_TYPE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
GRAPH_TO_PROMPT_JS = """
async (workflow) => {
    const app = window.comfyAPI?.app?.app;
    if (!app) return { ok: false, error: 'comfyAPI.app.app missing' };
    const graphNodes = () => app.graph?.nodes || app.graph?._nodes || [];
    const expectedTypes = [...new Set((workflow?.nodes || []).map((node) => node.type).filter(Boolean))];
    const registeredTable = () => window.LiteGraph?.registered_node_types || {};
    const isUnknownName = (name) => !name || name === 'UNKNOWN' || String(name).startsWith('UNKNOWN_');
    const nodeDataReady = (type) => {
        const ctor = registeredTable()[type];
        const data = ctor?.nodeData || ctor?.prototype?.nodeData;
        return Boolean(data?.input?.required);
    };
    const widgetsNamed = (node) => {
        const widgets = node.widgets || [];
        return widgets.every((widget) => widget && !isUnknownName(widget.name));
    };
    try {
        let registered = [];
        let defined = [];
        for (let i = 0; i < 80; i++) {
            registered = expectedTypes.filter((type) => Boolean(registeredTable()[type]));
            defined = expectedTypes.filter((type) => nodeDataReady(type));
            if (expectedTypes.length > 0 && defined.length === expectedTypes.length) break;
            await new Promise((resolve) => setTimeout(resolve, 250));
        }
        await app.loadGraphData(workflow);
        let loadedTypes = [];
        for (let i = 0; i < 80; i++) {
            await new Promise((resolve) => setTimeout(resolve, 250));
            const nodes = graphNodes();
            loadedTypes = nodes.map((node) => String(node.type || node.comfyClass || ''));
            const ready = expectedTypes.length > 0 && expectedTypes.every((type) => loadedTypes.includes(type));
            if (ready && nodes.every(widgetsNamed)) break;
        }
        const graphReady = expectedTypes.length > 0 && expectedTypes.every((type) => loadedTypes.includes(type));
        if (expectedTypes.length > 0 && !graphReady) {
            return {
                ok: false,
                error: 'loadGraphData did not load expected node types',
                loadedTypes,
                expectedTypes,
                registered,
                defined,
            };
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
            return { ok: false, error: 'graphToPrompt failed', missing, loadedTypes, expectedTypes, registered, defined };
        }
        for (const node of graphNodes()) {
            const entry = prompt[String(node.id)];
            if (!entry || typeof entry !== 'object') continue;
            const type = node.type || node.comfyClass;
            if (type && !entry.class_type) entry.class_type = type;
            if (node.title) {
                entry._meta = entry._meta || {};
                if (!entry._meta.title) entry._meta.title = node.title;
            }
            const inputs = entry.inputs || {};
            const unknownKeys = Object.keys(inputs).filter((key) => isUnknownName(key));
            const widgets = (node.widgets || []).filter((widget) => widget && !isUnknownName(widget.name));
            if (!unknownKeys.length || !widgets.length) continue;
            const named = {};
            for (const [key, value] of Object.entries(inputs)) {
                if (!isUnknownName(key)) named[key] = value;
            }
            unknownKeys.forEach((key, index) => {
                const name = widgets[index]?.name;
                if (name && named[name] === undefined) named[name] = inputs[key];
            });
            entry.inputs = named;
        }
        return {
            ok: true,
            prompt,
            missing,
            node_count: Object.keys(prompt).length,
            loaded_types: loadedTypes,
            expected_types: expectedTypes,
            registered_types: registered,
            defined_types: defined,
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


def _skip_ready_type(name: str) -> bool:
    return (
        (not name)
        or name in SKIP_OBJECT_INFO_TYPES
        or name.startswith("Primitive")
        or bool(SUBGRAPH_TYPE_RE.match(name))
    )


def iter_class_types(payload: Any) -> list[str]:
    """Collect UI ``type`` / API ``class_type`` names, including subgraphs."""
    found: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            class_type = obj.get("class_type")
            if isinstance(class_type, str) and class_type.strip():
                found.add(class_type.strip())
            nodes = obj.get("nodes")
            if isinstance(nodes, list):
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    name = node.get("type") or node.get("class_type")
                    if isinstance(name, str) and name.strip():
                        found.add(name.strip())
                    walk(node)
            for key, value in obj.items():
                if key == "nodes":
                    continue
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(payload)
    return sorted(found)


def required_object_types(
    *,
    required_types: Iterable[str] | None = None,
    workflow: Mapping[str, Any] | None = None,
    lock: Mapping[str, Any] | None = None,
) -> list[str]:
    types: set[str] = set()
    if required_types:
        types.update(str(item).strip() for item in required_types if str(item).strip())
    if workflow is not None:
        types.update(iter_class_types(workflow))
    if lock is not None:
        types.update(iter_class_types(lock))
    return sorted(name for name in types if not _skip_ready_type(name))


def missing_object_types(
    info: Mapping[str, Any] | None,
    required: Iterable[str],
) -> list[str]:
    present = info if isinstance(info, Mapping) else {}
    return [name for name in required if name not in present]


def wait_ready(
    base: str,
    timeout: int = 900,
    *,
    required_types: Iterable[str] | None = None,
    workflow: Mapping[str, Any] | None = None,
    lock: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Wait for ``/system_stats``, then for lock/workflow ``class_type``s in ``/object_info``."""
    needed = required_object_types(
        required_types=required_types,
        workflow=workflow,
        lock=lock,
    )
    deadline = time.time() + timeout
    last_error: Exception | None = None
    stats: dict[str, Any] | None = None
    while time.time() < deadline:
        try:
            stats = http_json(f"{base.rstrip('/')}/system_stats", timeout=20)
            if not isinstance(stats, dict):
                stats = {}
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(2)
            continue
        missing = missing_object_types(fetch_object_info(base), needed) if needed else []
        if not missing:
            devices = [device.get("name") for device in (stats.get("devices") or [])]
            print(
                json.dumps({"ready": True, "devices": devices, "object_types": needed}),
                flush=True,
            )
            return stats
        last_error = TimeoutError("missing object_info types: " + ",".join(missing))
        print(json.dumps({"ready": False, "missing": missing}), flush=True)
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


def enable_glb_export(
    workflow: dict[str, Any],
    types: set[str] | None = None,
) -> dict[str, Any]:
    """Official TripoSplat template bypasses mesh/GLB export; turn those nodes on."""
    wanted = types or ENABLE_GLB_TYPES
    for _container, nodes in iter_node_lists(workflow):
        for node in nodes:
            if isinstance(node, dict) and node.get("type") in wanted:
                node["mode"] = 0
    return workflow


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
            "/usr/local/bin/google-chrome",
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


_PRIMITIVE_WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}


def _is_unknown_input_key(key: str) -> bool:
    return key == "UNKNOWN" or key.startswith("UNKNOWN_")


_CONTROL_AFTER_GENERATE = frozenset({"fixed", "increment", "decrement", "randomize"})


def _is_widget_spec(spec: Any) -> bool:
    if not isinstance(spec, list | tuple) or not spec:
        return False
    first = spec[0]
    opts = spec[1] if len(spec) > 1 and isinstance(spec[1], Mapping) else {}
    if opts.get("forceInput"):
        return False
    return isinstance(first, list | tuple) or first in _PRIMITIVE_WIDGET_TYPES


def widget_input_names(node_def: Mapping[str, Any] | None) -> list[str]:
    """Widget names in ComfyUI INPUT_TYPES order (required then optional)."""
    names: list[str] = []
    inputs = (node_def or {}).get("input") if isinstance(node_def, Mapping) else None
    if not isinstance(inputs, Mapping):
        return names
    for section in ("required", "optional"):
        block = inputs.get(section)
        if not isinstance(block, Mapping):
            continue
        for name, spec in block.items():
            if _is_widget_spec(spec):
                names.append(str(name))
    return names


def _drop_control_after_generate(values: list[Any]) -> list[Any]:
    cleaned: list[Any] = []
    index = 0
    while index < len(values):
        cleaned.append(values[index])
        if (
            index + 1 < len(values)
            and str(values[index + 1]).lower() in _CONTROL_AFTER_GENERATE
        ):
            index += 2
            continue
        index += 1
    return cleaned


def ui_workflow_to_api_prompt(
    workflow: Mapping[str, Any],
    object_info: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an API prompt from UI nodes + ``/object_info`` without Playwright.

    ``graphToPrompt()`` can convert the default welcome graph when
    ``loadGraphData`` does not replace it. Widget order follows INPUT_TYPES;
    ``forceInput`` sockets and leftover frontend widgets are skipped.
    """
    nodes = [node for node in (workflow.get("nodes") or ()) if isinstance(node, dict)]
    nodes_by_id = {int(node["id"]): node for node in nodes if node.get("id") is not None}
    links_by_dest: dict[tuple[int, str], list[Any]] = {}
    for raw in workflow.get("links") or ():
        if not isinstance(raw, list | tuple) or len(raw) < 6:
            continue
        _link_id, src, src_slot, dest, dest_slot, _type = raw[:6]
        dest_node = nodes_by_id.get(int(dest))
        dest_inputs = dest_node.get("inputs") or [] if dest_node else []
        if not isinstance(dest_inputs, list) or int(dest_slot) >= len(dest_inputs):
            continue
        name = dest_inputs[int(dest_slot)].get("name") if isinstance(dest_inputs[int(dest_slot)], Mapping) else None
        if name:
            links_by_dest[(int(dest), str(name))] = [str(src), int(src_slot)]
    prompt: dict[str, Any] = {}
    for node in nodes:
        if node.get("mode", 0) != 0 or node.get("id") is None:
            continue
        class_type = str(node.get("type") or "")
        names = widget_input_names(object_info.get(class_type) if isinstance(object_info, Mapping) else None)
        values = _drop_control_after_generate(list(node.get("widgets_values") or ()))
        inputs = {name: value for name, value in zip(names, values, strict=False)}
        for (dest, name), ref in links_by_dest.items():
            if dest == int(node["id"]):
                inputs[name] = ref
        prompt[str(node["id"])] = {
            "class_type": class_type,
            "inputs": inputs,
            "_meta": {"title": str(node.get("title") or class_type)},
        }
    return prompt


def _prompt_covers_ui(prompt: Mapping[str, Any] | None, workflow: Mapping[str, Any]) -> bool:
    if not isinstance(prompt, Mapping) or not prompt:
        return False
    wanted = {
        str(node.get("type"))
        for node in (workflow.get("nodes") or ())
        if isinstance(node, dict)
        and node.get("mode", 0) == 0
        and node.get("type")
        and str(node.get("type")) not in SKIP_OBJECT_INFO_TYPES
    }
    have = {
        str(node.get("class_type"))
        for node in prompt.values()
        if isinstance(node, dict) and node.get("class_type")
    }
    return bool(wanted) and wanted <= have


def repair_converted_prompt(
    prompt: dict[str, Any],
    ui_workflow: Mapping[str, Any] | None = None,
    object_info: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fill class_type / widget names when graphToPrompt emits UNKNOWN keys.

    GitHub custom nodes can load on the graph (``node.type`` is set) while
    ``constructor.nodeData`` is still empty, so the API prompt comes back with
    ``class_type: null`` and ``UNKNOWN`` / ``UNKNOWN_1`` widgets.
    """
    ui_nodes = {
        str(node.get("id")): node
        for node in (ui_workflow or {}).get("nodes") or ()
        if isinstance(node, dict)
    }
    for node_id, entry in prompt.items():
        if not isinstance(entry, dict):
            continue
        ui_node = ui_nodes.get(str(node_id)) or {}
        class_type = entry.get("class_type") or ui_node.get("type")
        if class_type:
            entry["class_type"] = class_type
        title = ((entry.get("_meta") or {}) if isinstance(entry.get("_meta"), dict) else {}).get(
            "title"
        ) or ui_node.get("title")
        if title:
            entry.setdefault("_meta", {})
            if isinstance(entry["_meta"], dict) and not entry["_meta"].get("title"):
                entry["_meta"]["title"] = title
        inputs = entry.setdefault("inputs", {})
        if not isinstance(inputs, dict):
            continue
        unknown_keys = [key for key in inputs if _is_unknown_input_key(str(key))]
        if not unknown_keys or not class_type:
            continue
        named = {key: value for key, value in inputs.items() if key not in unknown_keys}
        info = object_info.get(str(class_type)) if isinstance(object_info, Mapping) else None
        for key, name in zip(unknown_keys, widget_input_names(info), strict=False):
            if name not in named:
                named[name] = inputs[key]
        entry["inputs"] = named
    return prompt


def fetch_object_info(base: str) -> dict[str, Any]:
    for path in ("/object_info", "/api/object_info"):
        try:
            payload = http_json(f"{base.rstrip('/')}{path}", timeout=120)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError):
            continue
        if isinstance(payload, dict) and payload:
            return payload
    return {}


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
    info = fetch_object_info(base)
    prompt = result.get("prompt") if isinstance(result, Mapping) else None
    via = "graphToPrompt"
    if not result.get("ok") or not isinstance(prompt, dict) or not _prompt_covers_ui(prompt, workflow):
        if not info:
            raise RuntimeError(f"browser convert failed: {result}")
        print(
            json.dumps(
                {
                    "browser_convert": False,
                    "error": (result or {}).get("error"),
                    "loaded_types": (result or {}).get("loadedTypes")
                    or (result or {}).get("loaded_types"),
                }
            ),
            flush=True,
        )
        prompt = ui_workflow_to_api_prompt(workflow, info)
        via = "object_info"
    prompt = repair_converted_prompt(prompt, workflow, info)
    typed = [
        node.get("class_type")
        for node in prompt.values()
        if isinstance(node, dict)
    ]
    unknown = [
        node_id
        for node_id, node in prompt.items()
        if isinstance(node, dict)
        and any(_is_unknown_input_key(str(key)) for key in (node.get("inputs") or {}))
    ]
    print(
        json.dumps(
            {
                "converted": True,
                "via": via,
                "node_count": len(prompt),
                "missing": result.get("missing") if isinstance(result, Mapping) else [],
                "loaded_types": result.get("loaded_types") if isinstance(result, Mapping) else [],
                "registered_types": result.get("registered_types") if isinstance(result, Mapping) else [],
                "defined_types": result.get("defined_types") if isinstance(result, Mapping) else [],
                "repaired": any(isinstance(name, str) and name for name in typed),
                "unknown_input_nodes": unknown,
            }
        ),
        flush=True,
    )
    if not typed or not all(isinstance(name, str) and name for name in typed):
        raise RuntimeError("graphToPrompt left class_type empty after repair")
    if unknown:
        raise RuntimeError(
            "graphToPrompt left UNKNOWN widget names after repair: "
            + ",".join(unknown)
        )
    if not _prompt_covers_ui(prompt, workflow):
        raise RuntimeError("converted prompt is missing UI node types")
    return prompt


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
SEED_TYPES = SAMPLER_TYPES | {"RandomNoise", "SAM3DGenerateSLAT"}
SCHEDULER_TYPES = {"Flux2Scheduler", "Ideogram4Scheduler", "Cosmos3Scheduler"}
GUIDER_TYPES = {"CFGGuider", "DualModelGuider"}
SIZE_CLASS_TYPES = {
    "Cosmos3EmptyAVLatentVideo",
    "Cosmos3EmptyLatentVideo",
    "Cosmos3ImageToVideo",
    "Cosmos3TextEncode",
}
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
        if class_type in SAMPLER_TYPES | SCHEDULER_TYPES | GUIDER_TYPES:
            for key in ("steps", "cfg", "denoise"):
                if key in wanted and key in inputs:
                    inputs[key] = wanted[key]
        if (
            ("Empty" in class_type and "Latent" in class_type)
            or class_type in SCHEDULER_TYPES
            or class_type in SIZE_CLASS_TYPES
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
    class_type = str(node.get("class_type") or "")
    if "text" in inputs or class_type.startswith("CLIPText"):
        return "text"
    if "prompt" in inputs or class_type == "Cosmos3TextEncode":
        return "prompt"
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


def iter_mesh_names(obj: Any) -> list[str]:
    """Collect mesh/splat paths hidden in history ``result`` / ``text`` / nested lists."""
    names: list[str] = []
    if isinstance(obj, str):
        path = obj.replace("\\", "/")
        if Path(path).suffix.lower() in MESH_SUFFIXES:
            names.append(path)
    elif isinstance(obj, Mapping):
        for value in obj.values():
            names.extend(iter_mesh_names(value))
    elif isinstance(obj, list | tuple):
        for item in obj:
            names.extend(iter_mesh_names(item))
    return names


def _output_view_parts(path: str) -> tuple[str, str]:
    """Split ``.../output/<subfolder>/<file>`` into ``(filename, subfolder)``."""
    normalized = path.replace("\\", "/").strip()
    name = Path(normalized).name
    if not name:
        return "", ""
    parts = [part for part in normalized.split("/") if part]
    if "output" in parts:
        rel = parts[parts.index("output") + 1 :]
        if rel:
            return rel[-1], "/".join(rel[:-1])
    return name, ""


def _as_view_item(raw: Any) -> dict[str, str] | None:
    if isinstance(raw, str):
        filename, subfolder = _output_view_parts(raw)
        if not filename:
            return None
        return {"filename": filename, "subfolder": subfolder, "type": "output"}
    if isinstance(raw, Mapping) and raw.get("filename"):
        filename = str(raw["filename"]).replace("\\", "/")
        subfolder = str(raw.get("subfolder") or "")
        if not subfolder and ("/" in filename or "\\" in filename):
            filename, subfolder = _output_view_parts(filename)
        return {
            "filename": Path(filename).name,
            "subfolder": subfolder,
            "type": str(raw.get("type") or "output"),
        }
    return None


def history_view_items(history: Mapping[str, Any]) -> list[dict[str, str]]:
    """Turn ComfyUI ``/history`` outputs into ``/view`` query items.

    Official Save* nodes use ``images`` / ``gifs`` / ``videos``. TRELLIS.2 and
    Pixal3D put a filesystem path in ``result`` or ``text`` instead.
    """
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(raw: Any) -> None:
        item = _as_view_item(raw)
        if item is None:
            return
        name = Path(item["filename"]).name
        if not name or name in {".", ".."}:
            return
        key = (name, item["subfolder"], item["type"])
        if key in seen:
            return
        seen.add(key)
        items.append({**item, "filename": name})

    for node_output in (history.get("outputs") or {}).values():
        if not isinstance(node_output, Mapping):
            continue
        for key in OUTPUT_KEYS:
            for raw in node_output.get(key) or []:
                add(raw)
    for path in iter_mesh_names(history):
        add(path)
    return items


def download_outputs(base: str, history: dict[str, Any], dest: Path) -> list[Path]:
    saved: list[Path] = []
    dest.mkdir(parents=True, exist_ok=True)
    root = base.rstrip("/")
    for item in history_view_items(history):
        query = urllib.parse.urlencode(
            {
                "filename": item["filename"],
                "subfolder": item["subfolder"],
                "type": item["type"],
            }
        )
        path = safe_dest_file(dest, item["filename"])
        try:
            with urllib.request.urlopen(f"{root}/view?{query}", timeout=300) as response:
                path.write_bytes(response.read())
        except urllib.error.HTTPError as exc:
            print(
                json.dumps(
                    {
                        "view_error": exc.code,
                        "filename": item["filename"],
                        "subfolder": item["subfolder"],
                    }
                ),
                flush=True,
            )
            continue
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
    enable_glb: bool = False,
) -> list[dict[str, Any]]:
    out.mkdir(parents=True, exist_ok=True)
    if enable_glb:
        workflow = enable_glb_export(json.loads(json.dumps(workflow)))
    stats = wait_ready(base, timeout=ready_timeout, workflow=workflow)
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
    parser.add_argument(
        "--enable-glb",
        action="store_true",
        help="un-bypass SplatToMesh / SaveGLB (TripoSplat official template)",
    )
    parser.add_argument("--no-glb", action="store_true")
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
        enable_glb=bool(args.enable_glb) and not args.no_glb,
    )


if __name__ == "__main__":
    main()
