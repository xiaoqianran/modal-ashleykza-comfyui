"""One Studio run = one recipe attempt, with a call-chain of spans.

Developer: add a model, hydrate, hit an error, forget to stop — the leftover
GPU/CPU occupancy is the bill, not just the successful /prompt.

Maintainer: instrument Studio jobs once via ``track``. Nested ``span`` is
opt-in timeline. Probe is off in unit tests until ``enable_modal_sidecar``.
Never imported by the GPU Image.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studio import cost as rates

SCHEMA = 1
WATCH_SECONDS = 60.0
_CURRENT: ContextVar[dict[str, Any] | None] = ContextVar("studio_cost_run", default=None)
_LOCK = threading.Lock()
def _noop_list() -> list[dict[str, Any]]:
    return []


def _noop_stop(**_kwargs: Any) -> list[str]:
    return []


_PROBE_LIST: Callable[[], list[dict[str, Any]]] = _noop_list
_PROBE_STOP: Callable[..., list[str]] = _noop_stop


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _root() -> Path:
    return rates.TRACE_PATH.parent


def _runs_dir() -> Path:
    return _root() / "runs"


def _active_path() -> Path:
    return _root() / "active-run.json"


def _run_path(run_id: str) -> Path:
    return _runs_dir() / f"{run_id}.json"


def enable_modal_sidecar() -> None:
    """Wire leftover probe to Modal CLI. Call from Studio ``main()`` only."""
    global _PROBE_LIST, _PROBE_STOP
    from studio.modal_ops import list_workspace_containers, stop_workspace_containers

    _PROBE_LIST = list_workspace_containers
    _PROBE_STOP = stop_workspace_containers


def probe_containers() -> list[dict[str, Any]]:
    try:
        return list(_PROBE_LIST())
    except Exception:
        return []


def reclaim_leftovers(*, roles: tuple[str, ...] = ("gpu", "cpu"), log: Any | None = None) -> list[str]:
    try:
        return list(_PROBE_STOP(roles=roles, log=log))
    except Exception:
        return []


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _save_run(run: dict[str, Any]) -> None:
    _recompute(run)
    dest = _run_path(str(run["run_id"]))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _active_path().write_text(
        json.dumps({"run_id": run["run_id"]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_active() -> dict[str, Any] | None:
    pointer = _load_json(_active_path()) or {}
    run_id = str(pointer.get("run_id") or "")
    if not run_id:
        return None
    return _load_json(_run_path(run_id))


def recent_runs(limit: int = 20) -> list[dict[str, Any]]:
    directory = _runs_dir()
    if not directory.is_dir():
        return []
    files = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    cap = max(int(limit), 1)
    out: list[dict[str, Any]] = []
    for path in files[:cap]:
        run = _load_json(path)
        if run:
            out.append(public_run(run))
    return out


def _new_run(*, recipe: str, gpu: str, trigger: str, keep_gpu: bool) -> dict[str, Any]:
    gpu_name = rates.normalize_gpu(gpu) or rates.normalize_gpu(rates.default_gpu(recipe))
    return {
        "schema": SCHEMA,
        "run_id": uuid.uuid4().hex[:12],
        "recipe": recipe or None,
        "gpu": gpu_name,
        "trigger": trigger,
        "status": "running",
        "keep_gpu": bool(keep_gpu),
        "expect_gpu": False,
        "started": _now(),
        "finished": None,
        "spans": [],
        "leftovers": [],
        "meter_ts": None,
        "usd": 0.0,
        "seconds": 0.0,
        "jobs": 0,
        "burn_usd_per_min": 0.0,
    }


def _open_run(*, recipe: str, gpu: str, trigger: str, keep_gpu: bool) -> dict[str, Any]:
    existing = load_active()
    recipe_id = str(recipe or "").strip()
    gpu_name = rates.normalize_gpu(gpu) or rates.normalize_gpu(rates.default_gpu(recipe_id))
    if (
        existing
        and existing.get("status") in {"running", "leaking", "kept"}
        and (not recipe_id or existing.get("recipe") == recipe_id)
    ):
        if gpu_name:
            existing["gpu"] = gpu_name
        existing["keep_gpu"] = bool(keep_gpu) or bool(existing.get("keep_gpu"))
        existing["trigger"] = trigger
        return existing
    return _new_run(recipe=recipe_id, gpu=gpu_name, trigger=trigger, keep_gpu=keep_gpu)


def _span_usd(resource: str, seconds: float, gpu: str, billable: bool) -> float:
    if not billable:
        return 0.0
    if resource == "gpu" and gpu:
        try:
            return rates.usd_for_seconds(gpu, seconds)
        except ValueError:
            return 0.0
    if resource == "cpu":
        return rates.usd_for_cpu(seconds)
    return 0.0


def _recompute(run: dict[str, Any]) -> None:
    usd = 0.0
    seconds = 0.0
    for item in run.get("spans") or []:
        if not isinstance(item, dict) or not item.get("billable"):
            continue
        usd += float(item.get("usd") or 0)
        seconds += float(item.get("seconds") or 0)
    run["usd"] = round(usd, 6)
    run["seconds"] = round(seconds, 3)
    run["burn_usd_per_min"] = _burn_per_min(str(run.get("gpu") or ""), run.get("leftovers") or [])


def _burn_per_min(gpu: str, leftovers: list[Any]) -> float:
    total = 0.0
    roles = {str(item.get("role") or "") for item in leftovers if isinstance(item, dict)}
    if "gpu" in roles and gpu:
        try:
            total += rates.usd_per_second(gpu) * 60
        except ValueError:
            pass
    if "cpu" in roles:
        total += rates.usd_for_cpu(60)
    return round(total, 6)


def _append_span(
    run: dict[str, Any],
    *,
    name: str,
    resource: str,
    seconds: float,
    status: str,
    error: str | None,
    billable: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gpu = str(run.get("gpu") or "")
    item = {
        "name": name,
        "resource": resource,
        "seconds": round(max(float(seconds), 0.0), 3),
        "usd": _span_usd(resource, seconds, gpu, billable),
        "status": status,
        "error": error,
        "billable": bool(billable),
        "ts": _now(),
    }
    if extra:
        item["extra"] = extra
    run.setdefault("spans", []).append(item)
    if status == "error":
        run["status"] = "error"
    _recompute(run)
    _save_run(run)
    try:
        rates.record_event(
            {
                "kind": "span",
                "run_id": run["run_id"],
                "recipe": run.get("recipe"),
                "gpu": run.get("gpu"),
                **{key: item[key] for key in ("name", "resource", "seconds", "usd", "status", "error")},
            }
        )
    except Exception:
        pass
    return item


@contextmanager
def span(
    name: str,
    *,
    resource: str = "gpu",
    billable: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> Iterator[None]:
    """Record a call-chain step. No-op when no run is active (unit tests)."""
    charge = resource in {"gpu", "cpu"} if billable is None else bool(billable)
    run = _CURRENT.get()
    started = time.monotonic()
    status = "ok"
    error: str | None = None
    try:
        yield
    except Exception as exc:
        status = "error"
        error = str(exc)[:800]
        raise
    finally:
        if run is not None:
            _append_span(
                run,
                name=name,
                resource=resource,
                seconds=time.monotonic() - started,
                status=status,
                error=error,
                billable=charge,
                extra=extra,
            )


def _resource_for(kind: str) -> tuple[str, bool]:
    if kind == "hydrate":
        return "cpu", True
    if kind == "generate":
        return "gpu", True
    return "control", False


def _expect_gpu(kind: str, keep_gpu: bool, result: dict[str, Any] | None) -> bool:
    if keep_gpu:
        return True
    mode = str((result or {}).get("gpu_mode") or "")
    return kind == "serve" and mode == "serve"


def _apply_leftovers(
    run: dict[str, Any],
    leftovers: list[dict[str, Any]],
    *,
    expect_gpu: bool,
    close: bool = False,
    now: float | None = None,
) -> None:
    run["leftovers"] = leftovers
    unexpected = [row for row in leftovers if row.get("role") == "cpu"]
    if not expect_gpu:
        unexpected.extend(row for row in leftovers if row.get("role") == "gpu")
    if not leftovers:
        if expect_gpu:
            run["status"] = "kept"
            run["expect_gpu"] = True
            run["meter_ts"] = run.get("meter_ts") or time.time()
            _recompute(run)
            return
        run["expect_gpu"] = False
        run["meter_ts"] = None
        if close:
            if run.get("status") in {"leaking", "kept", "running"}:
                run["status"] = "ok"
            run["finished"] = run.get("finished") or _now()
        else:
            run["status"] = "running"
            run["finished"] = None
        _recompute(run)
        return
    if expect_gpu and not unexpected:
        run["status"] = "kept"
        run["expect_gpu"] = True
    else:
        run["status"] = "leaking"
        run["expect_gpu"] = expect_gpu
    meter = run.get("meter_ts")
    clock = time.time() if now is None else now
    if meter:
        elapsed = max(clock - float(meter), 0.0)
        if elapsed >= 1:
            gpu_left = any(row.get("role") == "gpu" for row in leftovers)
            cpu_left = any(row.get("role") == "cpu" for row in leftovers)
            name = "held" if run.get("status") == "kept" else "leftover"
            if gpu_left:
                _append_span(
                    run,
                    name=f"{name}_gpu",
                    resource="gpu",
                    seconds=elapsed,
                    status=run["status"],
                    error=None,
                    billable=True,
                    extra={"containers": leftovers},
                )
            if cpu_left:
                _append_span(
                    run,
                    name=f"{name}_cpu",
                    resource="cpu",
                    seconds=elapsed,
                    status=run["status"],
                    error=None,
                    billable=True,
                    extra={"containers": leftovers},
                )
    run["meter_ts"] = clock
    _recompute(run)


def public_run(run: dict[str, Any]) -> dict[str, Any]:
    _recompute(run)
    hint = format_run_hint(run)
    return {
        "schema": SCHEMA,
        "kind": run.get("trigger") or "run",
        "run_id": run.get("run_id"),
        "recipe": run.get("recipe"),
        "gpu": run.get("gpu"),
        "status": run.get("status"),
        "keep_gpu": bool(run.get("keep_gpu")),
        "jobs": int(run.get("jobs") or 0),
        "seconds": run.get("seconds"),
        "billable_seconds": run.get("seconds"),
        "usd": run.get("usd"),
        "burn_usd_per_min": run.get("burn_usd_per_min"),
        "leftovers": run.get("leftovers") or [],
        "spans": run.get("spans") or [],
        "started": run.get("started"),
        "finished": run.get("finished"),
        "hint": hint,
    }


def format_run_hint(run: dict[str, Any]) -> str:
    _recompute(run)
    parts = [
        f"本次 {rates.format_usd(float(run.get('usd') or 0))}",
        f"{float(run.get('seconds') or 0):.0f}s",
    ]
    if run.get("gpu"):
        parts.append(str(run["gpu"]))
    status = str(run.get("status") or "")
    if status == "leaking":
        parts.append(f"容器还在跑 {rates.format_usd(float(run.get('burn_usd_per_min') or 0))}/min")
    elif status == "kept":
        parts.append(f"占卡中 {rates.format_usd(float(run.get('burn_usd_per_min') or 0))}/min")
    elif status == "error":
        parts.append("中途失败")
    names = [str(item.get("name") or "") for item in (run.get("spans") or []) if isinstance(item, dict)]
    errors = [
        str(item.get("name") or "")
        for item in (run.get("spans") or [])
        if isinstance(item, dict) and item.get("status") == "error"
    ]
    if errors:
        parts.append("失败 " + ", ".join(errors[-3:]))
    elif names:
        parts.append(" → ".join(names[-6:]))
    return " · ".join(part for part in parts if part)


def track(
    kind: str,
    fn: Callable[[], dict[str, Any]],
    *,
    job_id: str = "",
    payload: dict[str, Any] | None = None,
    log: Any | None = None,
    keep_gpu: bool = False,
) -> dict[str, Any]:
    """Wrap a Studio job. Always records the span, even when ``fn`` raises."""
    payload = payload or {}
    recipe = str(payload.get("catalog") or payload.get("recipe") or "").strip()
    gpu = str(payload.get("gpu") or "").strip()
    with _LOCK:
        run = _open_run(recipe=recipe, gpu=gpu, trigger=kind, keep_gpu=keep_gpu)
        _save_run(run)
    token = _CURRENT.set(run)
    result: dict[str, Any] | None = None
    resource, billable = _resource_for(kind)
    try:
        if kind == "hydrate":
            reclaimed = reclaim_leftovers(roles=("gpu", "cpu"), log=log)
            if reclaimed:
                _append_span(
                    run,
                    name="reclaim",
                    resource="control",
                    seconds=0,
                    status="ok",
                    error=None,
                    billable=False,
                    extra={"stopped": reclaimed},
                )
        with span(kind, resource=resource, billable=billable):
            result = fn()
        if not isinstance(result, dict):
            result = {}
        count = result.get("count")
        if isinstance(count, int) and count > 0:
            run["jobs"] = count
        if not run.get("gpu"):
            run["gpu"] = rates.normalize_gpu(str(result.get("gpu") or gpu))
        return result
    finally:
        try:
            expect = _expect_gpu(kind, keep_gpu, result)
            run["keep_gpu"] = bool(keep_gpu)
            leftovers = probe_containers()
            close = kind in {"generate", "stop"} and not expect
            _apply_leftovers(run, leftovers, expect_gpu=expect, close=close)
            roles: list[str] = []
            if any(row.get("role") == "cpu" for row in leftovers):
                roles.append("cpu")
            if not expect and any(row.get("role") == "gpu" for row in leftovers):
                roles.append("gpu")
            if kind == "stop":
                roles = ["gpu", "cpu"]
            if roles:
                reclaim_leftovers(roles=tuple(roles), log=log)
                leftovers = probe_containers()
                _apply_leftovers(run, leftovers, expect_gpu=expect, close=close)
            summary = public_run(run)
            _save_run(run)
            if log:
                log(json.dumps({"cost": summary}, ensure_ascii=False))
            if isinstance(result, dict):
                result["cost"] = summary
        except Exception as exc:
            if log:
                log(f"cost trace skipped: {exc}")
        _CURRENT.reset(token)


def tick_leftovers() -> dict[str, Any] | None:
    """Charge occupancy since the last probe. Safe to call from a watchdog."""
    from studio import jobs as studio_jobs

    if studio_jobs.running():
        return load_active()
    run = load_active()
    leftovers = probe_containers()
    if run is None and not leftovers:
        return None
    if run is None:
        run = _new_run(recipe="", gpu="", trigger="leftover", keep_gpu=False)
    expect = bool(run.get("expect_gpu") or run.get("keep_gpu"))
    _apply_leftovers(run, leftovers, expect_gpu=expect)
    if run.get("status") == "leaking":
        reclaim_leftovers(roles=("gpu", "cpu"))
        leftovers = probe_containers()
        _apply_leftovers(run, leftovers, expect_gpu=False, close=not leftovers)
    _save_run(run)
    return run


def watch_leftovers(*, interval: float = WATCH_SECONDS) -> None:
    while True:
        time.sleep(max(float(interval), 5.0))
        try:
            tick_leftovers()
        except Exception:
            continue


def current_run() -> dict[str, Any] | None:
    return _CURRENT.get()
