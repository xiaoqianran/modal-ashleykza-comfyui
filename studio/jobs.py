"""In-memory background jobs for hydrate / serve / generate."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections.abc import Callable
from typing import Any

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


def create_job(kind: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "logs": [],
            "result": None,
            "error": None,
            "started": time.time(),
            "finished": None,
        }
    return job_id


def append_log(job_id: str, line: str) -> None:
    text = line.rstrip()
    if not text:
        return
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["logs"].append(text)
        if len(job["logs"]) > 400:
            job["logs"] = job["logs"][-400:]


def finish_job(job_id: str, result: Any = None, error: str | None = None) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job["status"] = "error" if error else "ok"
        job["result"] = result
        job["error"] = error
        job["finished"] = time.time()


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job is not None else None


def running() -> list[dict[str, Any]]:
    with _LOCK:
        return [dict(job) for job in _JOBS.values() if job.get("status") == "running"]


def spawn(kind: str, fn: Callable[[str], Any]) -> str:
    job_id = create_job(kind)

    def run() -> None:
        try:
            result = fn(job_id)
            finish_job(job_id, result=result)
        except Exception as exc:  # noqa: BLE001
            append_log(job_id, traceback.format_exc(limit=8))
            finish_job(job_id, error=str(exc))

    threading.Thread(target=run, name=f"studio-{kind}-{job_id}", daemon=True).start()
    return job_id
