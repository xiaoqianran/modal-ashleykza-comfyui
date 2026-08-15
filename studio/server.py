"""Local HTTP control plane. Bind 127.0.0.1 only."""

from __future__ import annotations

import argparse
import atexit
import json
import mimetypes
import random
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import workflow_queue
from catalog import (
    DEFAULT_CATALOG_ID,
    build_prompt,
    catalog_mode,
    has_param,
    image_params,
    list_catalogs,
    load_catalog,
    public_catalog,
    workflow_path,
)
from storage import safe_dest_file
from studio import jobs
from studio.comfy import queue_prompt, wait_history, wait_ready
from studio.keys import ALL_KEYS, ROOT, public_key_state, save_keys
from studio.modal_ops import (
    hydrate,
    load_state,
    runtime_status,
    save_state,
    start_gpu,
    stop_gpu,
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
UPLOAD_DIR = OUTPUT_DIR / "uploads"
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
IMAGE_SUFFIXES = ALLOWED_IMAGE_SUFFIXES


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


def save_upload(filename: str, data: bytes) -> Path:
    suffix = Path(filename.replace("\\", "/")).suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise ValueError(f"只接受图片文件：{sorted(ALLOWED_IMAGE_SUFFIXES)}")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"图片不能超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")
    if not data:
        raise ValueError("empty upload")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = safe_dest_file(UPLOAD_DIR, Path(filename.replace("\\", "/")).name)
    if dest.exists():
        dest = safe_dest_file(UPLOAD_DIR, f"{dest.stem}-{uuid.uuid4().hex[:8]}{suffix}")
    dest.write_bytes(data)
    return dest


def _image_names(catalog: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    raw = payload.get("images")
    names: list[str] = []
    if isinstance(raw, dict):
        for spec in image_params(catalog):
            value = raw.get(spec["id"])
            if isinstance(value, list):
                names.extend(str(item) for item in value if item)
            elif value:
                names.append(str(value))
    elif isinstance(raw, list):
        names = [str(item) for item in raw if item]
    elif isinstance(raw, str) and raw.strip():
        names = [raw.strip()]
    return names


def iter_generate_jobs(catalog: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    params = dict(payload.get("params") or {})
    prompts = payload.get("prompts")
    if isinstance(prompts, str):
        prompts = _split_prompts(prompts)
    prompts = [str(item).strip() for item in (prompts or []) if str(item).strip()]
    images = _image_names(catalog, payload)
    need_prompt = has_param(catalog, "prompt")
    need_image = any(spec.get("required") for spec in image_params(catalog))
    if need_prompt and not prompts:
        raise RuntimeError("至少需要一条提示词")
    if need_image and not images:
        raise RuntimeError("至少需要一张输入图")
    if not prompts:
        prompts = [""]
    if not images:
        images_or_none: list[str | None] = [None]
    else:
        images_or_none = list(images)
    if len(prompts) > 1 and len(images_or_none) > 1 and len(prompts) != len(images_or_none):
        raise RuntimeError("多提示词且多图时数量必须一致")
    jobs_spec: list[dict[str, Any]] = []
    if len(images_or_none) == 1:
        for prompt in prompts:
            jobs_spec.append({"prompt": prompt, "image": images_or_none[0], "params": params})
    elif len(prompts) == 1:
        for image in images_or_none:
            jobs_spec.append({"prompt": prompts[0], "image": image, "params": params})
    else:
        for prompt, image in zip(prompts, images_or_none, strict=True):
            jobs_spec.append({"prompt": prompt, "image": image, "params": params})
    return jobs_spec


def _resolve_upload(name: str) -> Path:
    path = safe_dest_file(UPLOAD_DIR, Path(str(name).replace("\\", "/")).name)
    if not path.is_file():
        raise RuntimeError(f"找不到已上传的图片: {path.name}")
    return path


def _run_generate_batch(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    recipe_id = str(payload.get("catalog") or load_state().get("catalog") or DEFAULT_CATALOG_ID)
    catalog = load_catalog(recipe_id)
    base = str(payload.get("base_url") or load_state().get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("还没有 ComfyUI 地址。先点「部署 GPU」，或粘贴已有的 *.modal.run")
    planned = iter_generate_jobs(catalog, payload)
    jobs.append_log(job_id, f"等待 {base} 就绪 · {catalog['title']} · {len(planned)} 个任务")
    workflow = None
    if catalog_mode(catalog) == "workflow":
        workflow = json.loads(workflow_path(catalog).read_text(encoding="utf-8"))
    elif isinstance(catalog.get("graph"), dict):
        workflow = catalog["graph"]
    ready = wait_ready(
        base,
        timeout=int(payload.get("ready_timeout") or 900),
        workflow=workflow,
    )
    jobs.append_log(job_id, json.dumps({"ready": True, "devices": ready.get("devices")}, ensure_ascii=False))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    template = None
    if catalog_mode(catalog) == "workflow":
        jobs.append_log(job_id, "用运行中的 ComfyUI 做 graphToPrompt()")
        try:
            template = workflow_queue.to_api_prompt(base, workflow)
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "workflow 模式需要本机 Playwright / Chrome 来跑 graphToPrompt。"
                "Z-Image 这种 mode=graph 的配方不需要。"
            ) from exc

    seed_base = (payload.get("params") or {}).get("seed", -1)
    results: list[dict[str, Any]] = []
    for index, item in enumerate(planned):
        bound = dict(item["params"])
        if item["prompt"]:
            bound["prompt"] = item["prompt"]
        if seed_base == -1 or seed_base is None:
            bound["seed"] = random.randint(0, 2**31 - 1)
        elif "seed" in bound:
            bound["seed"] = int(seed_base) + index
        image_name = None
        if item["image"]:
            local = _resolve_upload(str(item["image"]))
            image_name = workflow_queue.upload_image(base, local)
            jobs.append_log(job_id, f"uploaded {local.name} -> {image_name}")
        graph, values = build_prompt(
            catalog,
            bound,
            api_prompt=template,
            image_name=image_name,
        )
        jobs.append_log(
            job_id,
            f"[{index + 1}/{len(planned)}] seed={values.get('seed')} image={image_name or '-'}",
        )
        prompt_id = queue_prompt(base, graph, str(catalog.get("client_id") or "studio"))
        history = wait_history(base, prompt_id, timeout=900)
        saved = workflow_queue.download_outputs(base, history, OUTPUT_DIR)
        if not saved:
            raise RuntimeError(f"prompt {prompt_id} finished without outputs")
        files = [f"/api/outputs/{path.name}" for path in saved]
        images = [
            f"/api/outputs/{path.name}"
            for path in saved
            if path.suffix.lower() in IMAGE_SUFFIXES
        ]
        record = {
            "index": index,
            "prompt": item["prompt"],
            "seed": values.get("seed"),
            "prompt_id": prompt_id,
            "image": image_name,
            "files": files,
            "images": images or files,
        }
        results.append(record)
        jobs.append_log(job_id, json.dumps(record, ensure_ascii=False))
    save_state({"base_url": base, "catalog": recipe_id})
    return {
        "ok": True,
        "catalog": recipe_id,
        "count": len(results),
        "results": results,
        "devices": ready.get("devices"),
    }


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
                "任务结束，停止 GPU 容器。deploy 的 App 留着吃快照；不要开着 ComfyUI 页。",
            )
            stopped = stop_gpu(log=lambda line: jobs.append_log(job_id, line))
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
            _json(
                self,
                200,
                {"default": DEFAULT_CATALOG_ID, "catalogs": list_catalogs()},
            )
            return
        if path.startswith("/api/catalogs/"):
            recipe_id = path.removeprefix("/api/catalogs/").strip("/")
            try:
                catalog = load_catalog(recipe_id)
            except FileNotFoundError:
                _json(self, 404, {"error": f"unknown catalog: {recipe_id}"})
                return
            except ValueError as exc:
                _json(self, 400, {"error": str(exc)})
                return
            _json(self, 200, public_catalog(catalog))
            return
        if path.startswith("/api/uploads/"):
            name = Path(path.removeprefix("/api/uploads/")).name
            self._send_file(UPLOAD_DIR / name)
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
        if path == "/api/uploads":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                filename = self.headers.get("X-Filename") or "upload.png"
                data = self.rfile.read(length) if length else b""
                stored = save_upload(filename, data)
            except ValueError as exc:
                _json(self, 400, {"error": str(exc)})
                return
            _json(
                self,
                200,
                {
                    "ok": True,
                    "name": stored.name,
                    "url": f"/api/uploads/{stored.name}",
                    "bytes": stored.stat().st_size,
                },
            )
            return
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
            recipe_id = str(payload.get("catalog") or DEFAULT_CATALOG_ID)

            def run(job_id: str) -> dict[str, Any]:
                return hydrate(recipe_id, log=lambda line: jobs.append_log(job_id, line))

            _json(self, 200, {"job_id": jobs.spawn("hydrate", run)})
            return
        if path == "/api/serve":
            recipe_id = str(payload.get("catalog") or DEFAULT_CATALOG_ID)
            gpu = str(payload.get("gpu") or "")

            def run(job_id: str) -> dict[str, Any]:
                return start_gpu(recipe_id, gpu, log=lambda line: jobs.append_log(job_id, line))

            _json(self, 200, {"job_id": jobs.spawn("serve", run)})
            return
        if path == "/api/stop":
            result = stop_gpu()
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
        if path == "/api/catalog":
            recipe_id = str(payload.get("catalog") or DEFAULT_CATALOG_ID)
            try:
                catalog = load_catalog(recipe_id)
            except FileNotFoundError:
                _json(self, 404, {"error": f"unknown catalog: {recipe_id}"})
                return
            except ValueError as exc:
                _json(self, 400, {"error": str(exc)})
                return
            save_state({"catalog": recipe_id})
            _json(self, 200, {"ok": True, "catalog": public_catalog(catalog)})
            return
        if path == "/api/generate":
            _json(self, 200, {"job_id": jobs.spawn("generate", lambda job_id: _generate_batch(job_id, payload))})
            return
        _json(self, 404, {"error": "not found"})

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        path = path.resolve()
        allowed = (STATIC_DIR.resolve(), OUTPUT_DIR.resolve(), UPLOAD_DIR.resolve())
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local catalog control plane")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the default browser",
    )
    return parser.parse_args(argv)


def studio_url(host: str, port: int) -> str:
    shown = "127.0.0.1" if host in {"localhost", "::1"} else host
    return f"http://{shown}:{port}"


def open_browser(url: str) -> None:
    webbrowser.open(url)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("studio binds localhost only")
    url = studio_url(args.host, args.port)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Studio  {url}", flush=True)
    print("顶栏配方可选 Z-Image / Z-Image-Turbo / FLUX.2 [dev] / Qwen-Image-2512 / Qwen-Image-2512 Lightning / Krea-2 Turbo / Ideogram 4 / Cosmos3-Nano / Cosmos3-Edge / Cosmos3-Super / Cosmos3-Super-Text2Image / Cosmos3-Super-Text2Image-4Step / Cosmos3-Super-Image2Video / Cosmos3-Super-Image2Video-4Step / Pixal3D / Hunyuan3D 2.1 / TRELLIS.2 / TripoSplat。", flush=True)
    print("密钥只存在本机 .studio.env，不会进 Git。", flush=True)
    print("默认 GPU 是 L40S。启动走 modal deploy；生成结束后停残留容器，App 留着吃快照。", flush=True)
    atexit.register(stop_gpu)
    if not args.no_browser:
        threading.Timer(0.4, lambda: open_browser(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping GPU containers…", flush=True)
        stop_gpu()
        print("stopped", flush=True)


if __name__ == "__main__":
    main()
