"""Local HTTP control plane. Bind 127.0.0.1 only."""

from __future__ import annotations

import argparse
import atexit
import json
import mimetypes
import random
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from catalog import bind_graph, list_catalogs, load_catalog, param_defaults
from studio import jobs
from studio.comfy import download_images, queue_prompt, wait_history, wait_ready
from studio.keys import ALL_KEYS, ROOT, public_key_state, save_keys
from studio.modal_ops import (
    hydrate,
    load_state,
    runtime_status,
    save_state,
    start_serve,
    stop_serve,
)


def wants_keep_gpu(payload: dict[str, Any]) -> bool:
    """Leave the GPU up only when the user explicitly opts in."""
    raw = payload.get("keep_gpu")
    if isinstance(raw, bool):
        return raw
    if raw is None or raw == "":
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


STATIC_DIR = Path(__file__).resolve().parent / "static"
OUTPUT_DIR = ROOT / "artifacts" / "studio"


def _json(handler: BaseHTTPRequestHandler, code: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length) if length else b"{}"
    if not raw:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def _split_prompts(text: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip() == "---":
            joined = "\n".join(current).strip()
            if joined:
                chunks.append(joined)
            current = []
            continue
        current.append(line)
    joined = "\n".join(current).strip()
    if joined:
        chunks.append(joined)
    if len(chunks) == 1 and "\n" in text and all(len(part) < 400 for part in text.split("\n") if part.strip()):
        lines = [part.strip() for part in text.split("\n") if part.strip()]
        if len(lines) > 1:
            return lines
    return chunks


def _run_generate_batch(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    recipe_id = str(payload.get("catalog") or "z-image")
    catalog = load_catalog(recipe_id)
    base = str(payload.get("base_url") or load_state().get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("还没有 ComfyUI 地址。先启动 GPU，或粘贴已有的 *.modal.run")
    prompts = payload.get("prompts")
    if isinstance(prompts, str):
        prompts = _split_prompts(prompts)
    if not isinstance(prompts, list) or not prompts:
        raise RuntimeError("至少需要一条提示词")
    params = dict(payload.get("params") or {})
    jobs.append_log(job_id, f"等待 {base} 就绪")
    ready = wait_ready(base, timeout=int(payload.get("ready_timeout") or 900))
    jobs.append_log(job_id, json.dumps({"ready": True, "devices": ready.get("devices")}, ensure_ascii=False))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    seed_base = params.get("seed", -1)
    results: list[dict[str, Any]] = []
    for index, prompt in enumerate(prompts):
        text = str(prompt).strip()
        if not text:
            continue
        bound = dict(params)
        bound["prompt"] = text
        if seed_base == -1 or seed_base is None:
            bound["seed"] = random.randint(0, 2**31 - 1)
        else:
            bound["seed"] = int(seed_base) + index
        graph, values = bind_graph(catalog, bound)
        jobs.append_log(job_id, f"[{index + 1}/{len(prompts)}] seed={values['seed']}")
        prompt_id = queue_prompt(base, graph, str(catalog.get("client_id") or "studio"))
        history = wait_history(base, prompt_id, timeout=900)
        images = download_images(base, history, OUTPUT_DIR)
        if not images:
            raise RuntimeError(f"prompt {prompt_id} finished without images")
        item = {
            "index": index,
            "prompt": text,
            "seed": values["seed"],
            "prompt_id": prompt_id,
            "images": [f"/api/outputs/{path.name}" for path in images],
        }
        results.append(item)
        jobs.append_log(job_id, json.dumps(item, ensure_ascii=False))
    save_state({"base_url": base, "catalog": recipe_id})
    return {"ok": True, "count": len(results), "results": results, "devices": ready.get("devices")}


def _generate_batch(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    keep = wants_keep_gpu(payload)
    try:
        result = _run_generate_batch(job_id, payload)
        if keep:
            jobs.append_log(job_id, "keep_gpu=true，GPU 继续挂着")
        return result
    finally:
        if not keep:
            jobs.append_log(
                job_id,
                "任务结束，停止 GPU。scaledown 5s 挡不住 leftover modal serve。",
            )
            stopped = stop_serve(log=lambda line: jobs.append_log(job_id, line))
            jobs.append_log(
                job_id,
                json.dumps({"released": True, **stopped}, ensure_ascii=False),
            )


class Handler(BaseHTTPRequestHandler):
    server_version = "Studio/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"{self.address_string()} - {format % args}\n")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/index.html"}:
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            self._send_file(STATIC_DIR / path.removeprefix("/static/"))
            return
        if path.startswith("/api/outputs/"):
            name = Path(path.removeprefix("/api/outputs/")).name
            self._send_file(OUTPUT_DIR / name)
            return
        if path == "/api/catalogs":
            _json(self, 200, {"catalogs": list_catalogs()})
            return
        if path.startswith("/api/catalogs/"):
            recipe_id = path.removeprefix("/api/catalogs/").strip("/")
            try:
                catalog = load_catalog(recipe_id)
            except FileNotFoundError:
                _json(self, 404, {"error": f"unknown catalog: {recipe_id}"})
                return
            public = {
                key: catalog[key]
                for key in ("id", "title", "summary", "gpu", "gpu_choices", "params")
                if key in catalog
            }
            public["defaults"] = param_defaults(catalog)
            _json(self, 200, public)
            return
        if path == "/api/status":
            _json(
                self,
                200,
                {
                    "keys": public_key_state(),
                    "runtime": runtime_status(),
                },
            )
            return
        if path.startswith("/api/jobs/"):
            job = jobs.get_job(path.removeprefix("/api/jobs/").strip("/"))
            if job is None:
                _json(self, 404, {"error": "job not found"})
                return
            _json(self, 200, job)
            return
        _json(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            payload = _read_json(self)
        except (ValueError, json.JSONDecodeError) as exc:
            _json(self, 400, {"error": str(exc)})
            return
        if path == "/api/keys":
            updates = {
                key: str(payload.get(key) or "").strip()
                for key in ALL_KEYS
                if key in payload and str(payload.get(key) or "").strip()
            }
            save_keys(updates)
            _json(self, 200, {"ok": True, "keys": public_key_state()})
            return
        if path == "/api/hydrate":
            recipe_id = str(payload.get("catalog") or "z-image")

            def run(job_id: str) -> dict[str, Any]:
                return hydrate(recipe_id, log=lambda line: jobs.append_log(job_id, line))

            _json(self, 200, {"job_id": jobs.spawn("hydrate", run)})
            return
        if path == "/api/serve":
            recipe_id = str(payload.get("catalog") or "z-image")
            gpu = str(payload.get("gpu") or "")

            def run(job_id: str) -> dict[str, Any]:
                return start_serve(recipe_id, gpu, log=lambda line: jobs.append_log(job_id, line))

            _json(self, 200, {"job_id": jobs.spawn("serve", run)})
            return
        if path == "/api/stop":
            result = stop_serve()
            _json(self, 200, result)
            return
        if path == "/api/base-url":
            url = str(payload.get("base_url") or "").rstrip("/")
            if url and not url.startswith("https://") and not url.startswith("http://"):
                _json(self, 400, {"error": "base_url must be http(s)"})
                return
            state = save_state({"base_url": url or None})
            _json(self, 200, {"ok": True, "runtime": {**runtime_status(), **{"base_url": state.get("base_url")}}})
            return
        if path == "/api/generate":
            _json(self, 200, {"job_id": jobs.spawn("generate", lambda job_id: _generate_batch(job_id, payload))})
            return
        _json(self, 404, {"error": "not found"})

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        path = path.resolve()
        allowed = (STATIC_DIR.resolve(), OUTPUT_DIR.resolve())
        if not any(path == root or root in path.parents for root in allowed):
            _json(self, 404, {"error": "not found"})
            return
        if not path.is_file():
            _json(self, 404, {"error": "not found"})
            return
        data = path.read_bytes()
        guessed = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", guessed)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="Z-Image studio control plane")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("studio binds localhost only")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Studio  http://{args.host}:{args.port}", flush=True)
    print("密钥只存在本机 .studio.env，不会进 Git。", flush=True)
    print("默认 GPU 是 T4；生成结束后会停掉 serve，避免空闲还计费。", flush=True)
    atexit.register(stop_serve)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping GPU…", flush=True)
        stop_serve()
        print("stopped", flush=True)


if __name__ == "__main__":
    main()
