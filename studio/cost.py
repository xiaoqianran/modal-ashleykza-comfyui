"""Frozen Modal rate card + generate estimate.

Call-chain occupancy (hydrate CPU, leftover GPU after errors) lives in
``studio.trace``. Neither module is imported by the GPU Image.
Updating the constants below is the only price maintenance.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studio.keys import ROOT

SCHEMA = 1
PRICE_AS_OF = "2026-08-12"
PRICE_SOURCE = "https://modal.com/pricing"
OVERLAY_PATH = ROOT / "benchmarks" / "models.json"
TRACE_PATH = ROOT / ".studio" / "cost-trace.jsonl"
DEFAULT_SCALEDOWN_SECONDS = 5.0

# USD per GPU-second. Hourly column is rate * 3600 (not a separate Modal unit).
GPU_USD_PER_SECOND: dict[str, float] = {
    "T4": 0.000164,
    "L4": 0.000222,
    "A10": 0.000306,
    "L40S": 0.000542,
    "A100-40GB": 0.000583,
    "A100-80GB": 0.000694,
    "RTX-PRO-6000": 0.000842,
    "H100": 0.001097,
    "H200": 0.001261,
    "B200": 0.001736,
    "B300": 0.001972,
}

# Hydrate ``sync_workflow``: cpu=8, memory=16384. Not GPU.
CPU_USD_PER_CORE_HOUR = 0.047
MEMORY_USD_PER_GIB_HOUR = 0.008
HYDRATE_CPU_CORES = 8.0
HYDRATE_MEMORY_GIB = 16.0

_GPU_ALIASES: dict[str, str] = {
    "A100": "A100-80GB",
    "A100 40GB": "A100-40GB",
    "A100-40": "A100-40GB",
    "A100 80GB": "A100-80GB",
    "A100-80": "A100-80GB",
    "NVIDIA L40S": "L40S",
    "NVIDIA-L40S": "L40S",
    "RTX PRO 6000": "RTX-PRO-6000",
    "RTX_PRO_6000": "RTX-PRO-6000",
    "TESLA T4": "T4",
}

_SECRET_KEY_PARTS = ("token", "secret", "password", "authorization", "api_key")


def normalize_gpu(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    return _GPU_ALIASES.get(raw.upper(), _GPU_ALIASES.get(raw, raw))


def usd_per_second(gpu: str) -> float:
    key = normalize_gpu(gpu)
    try:
        return GPU_USD_PER_SECOND[key]
    except KeyError as exc:
        known = ", ".join(GPU_USD_PER_SECOND)
        raise ValueError(f"unknown GPU {gpu!r}; known: {known}") from exc


def usd_for_seconds(gpu: str, seconds: float) -> float:
    return round(max(float(seconds), 0.0) * usd_per_second(gpu), 6)


def usd_for_cpu(
    seconds: float,
    *,
    cores: float = HYDRATE_CPU_CORES,
    memory_gib: float = HYDRATE_MEMORY_GIB,
) -> float:
    hours = max(float(seconds), 0.0) / 3600.0
    return round(
        hours * (float(cores) * CPU_USD_PER_CORE_HOUR + float(memory_gib) * MEMORY_USD_PER_GIB_HOUR),
        6,
    )


def format_usd(value: float | None) -> str:
    if value is None:
        return "—"
    number = float(value)
    if number >= 1:
        return f"${number:.2f}"
    if number >= 0.01:
        return f"${number:.3f}"
    return f"${number:.4f}"


def load_overlay(path: Path | None = None) -> dict[str, Any] | None:
    overlay_path = path or OVERLAY_PATH
    if not overlay_path.is_file():
        return None
    try:
        payload = json.loads(overlay_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def scaledown_seconds(overlay: dict[str, Any] | None = None) -> float:
    payload = overlay if overlay is not None else load_overlay()
    env = payload.get("environment") if isinstance(payload, dict) else None
    raw = env.get("scaledown_window_seconds") if isinstance(env, dict) else None
    try:
        value = float(raw) if raw is not None else DEFAULT_SCALEDOWN_SECONDS
    except (TypeError, ValueError):
        value = DEFAULT_SCALEDOWN_SECONDS
    return value if value > 0 else DEFAULT_SCALEDOWN_SECONDS


def overlay_row(recipe: str, overlay: dict[str, Any] | None = None) -> dict[str, Any] | None:
    payload = overlay if overlay is not None else load_overlay()
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None
    wanted = str(recipe or "").strip()
    for item in models:
        if isinstance(item, dict) and str(item.get("id") or "") == wanted:
            return item
    return None


def smoke_timing(recipe: str, overlay: dict[str, Any] | None = None) -> dict[str, Any] | None:
    row = overlay_row(recipe, overlay)
    smoke = row.get("smoke") if isinstance(row, dict) else None
    if not isinstance(smoke, dict) or str(smoke.get("status") or "") != "recorded":
        return None
    try:
        seconds = float(smoke.get("seconds"))
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    gpu = str(smoke.get("gpu") or "").strip() or None
    warm = smoke.get("warm_seconds")
    try:
        warm_seconds = float(warm) if warm is not None and warm != "" else None
    except (TypeError, ValueError):
        warm_seconds = None
    return {"seconds": seconds, "gpu": gpu, "warm_seconds": warm_seconds}


def default_gpu(recipe: str) -> str:
    if not recipe:
        return ""
    try:
        from catalog import load_catalog
    except ImportError:
        return ""
    try:
        catalog = load_catalog(recipe)
    except (FileNotFoundError, ValueError, OSError):
        return ""
    return str(catalog.get("gpu") or "").strip()


def _public_event(event: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in event.items():
        lowered = str(key).lower()
        if any(part in lowered for part in _SECRET_KEY_PARTS):
            continue
        if isinstance(value, str) and value.startswith(("hf_", "ak-", "as-")):
            continue
        out[key] = value
    return out


def predict(
    *,
    recipe: str = "",
    gpu: str = "",
    count: int = 1,
    keep_gpu: bool = False,
    overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recipe_id = str(recipe or "").strip()
    jobs = max(int(count), 1)
    gpu_name = normalize_gpu(gpu) or normalize_gpu(default_gpu(recipe_id))
    if not gpu_name:
        raise ValueError("gpu is required")
    rate = usd_per_second(gpu_name)
    payload = overlay if overlay is not None else load_overlay()
    idle = scaledown_seconds(payload)
    smoke = smoke_timing(recipe_id, payload) if recipe_id else None
    scaledown_usd = usd_for_seconds(gpu_name, idle)
    usd_minute = round(rate * 60, 6)
    usd_hour = round(rate * 3600, 6)
    hydrate_hour = usd_for_cpu(3600)
    notes = [
        "生成预估只计 GPU 秒，不含 Volume。",
        "准备权重按 hydrate CPU 8 核 / 16GiB 另计，见运行 trace。",
        "冒烟秒数是 POST /prompt → /history。生图墙钟含 wait_ready（冷启动）。",
        "报错或忘了停容器时，占用会继续写进同一条 run。",
    ]
    if keep_gpu:
        notes.append("勾了占卡后空闲也会一直计费，直到点停止。")
    if smoke:
        job_seconds = smoke["seconds"] * jobs
        billable = job_seconds + (0.0 if keep_gpu else idle)
        usd = usd_for_seconds(gpu_name, billable)
        smoke_gpu = smoke.get("gpu")
        hint = (
            f"约 {format_usd(usd)} · {gpu_name} · {jobs} 张 × {smoke['seconds']:.0f}s"
            f" + 缩容 {idle:.0f}s"
            f"；hydrate CPU {format_usd(hydrate_hour)}/h"
        )
        if smoke_gpu and normalize_gpu(str(smoke_gpu)) != gpu_name:
            hint += f"；秒数来自 {smoke_gpu} 冒烟"
        if keep_gpu:
            hint += " · 勾了占卡会一直计费"
        return {
            "schema": SCHEMA,
            "price_as_of": PRICE_AS_OF,
            "price_source": PRICE_SOURCE,
            "recipe": recipe_id or None,
            "gpu": gpu_name,
            "jobs": jobs,
            "mode": "recorded",
            "smoke_seconds": smoke["seconds"],
            "smoke_gpu": smoke_gpu,
            "warm_seconds": smoke.get("warm_seconds"),
            "job_seconds": round(job_seconds, 3),
            "scaledown_seconds": idle,
            "seconds": round(billable, 3),
            "usd": usd,
            "usd_per_second": rate,
            "usd_per_minute": usd_minute,
            "usd_per_hour": usd_hour,
            "scaledown_usd": scaledown_usd,
            "hydrate_usd_per_hour": hydrate_hour,
            "keep_gpu": keep_gpu,
            "excludes": ["volume"],
            "notes": notes,
            "hint": hint,
        }
    hint = (
        f"{gpu_name} {format_usd(usd_hour)}/h · 缩容 {idle:.0f}s ≈ {format_usd(scaledown_usd)}"
        f"；hydrate CPU {format_usd(hydrate_hour)}/h"
        "（尚无实测秒数，不编造任务总价）"
    )
    if keep_gpu:
        hint += " · 勾了占卡会一直计费"
    return {
        "schema": SCHEMA,
        "price_as_of": PRICE_AS_OF,
        "price_source": PRICE_SOURCE,
        "recipe": recipe_id or None,
        "gpu": gpu_name,
        "jobs": jobs,
        "mode": "rate_only",
        "smoke_seconds": None,
        "smoke_gpu": None,
        "warm_seconds": None,
        "job_seconds": None,
        "scaledown_seconds": idle,
        "seconds": None,
        "usd": None,
        "usd_per_second": rate,
        "usd_per_minute": usd_minute,
        "usd_per_hour": usd_hour,
        "scaledown_usd": scaledown_usd,
        "hydrate_usd_per_hour": hydrate_hour,
        "keep_gpu": keep_gpu,
        "excludes": ["volume"],
        "notes": notes,
        "hint": hint,
    }


def record_event(event: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    payload = _public_event(
        {
            "schema": SCHEMA,
            "ts": datetime.now(UTC).isoformat(),
            **event,
        }
    )
    dest = path or TRACE_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def recent_events(limit: int = 40, path: Path | None = None) -> list[dict[str, Any]]:
    dest = path or TRACE_PATH
    if not dest.is_file():
        return []
    try:
        lines = dest.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    cap = max(int(limit), 1)
    out: list[dict[str, Any]] = []
    for line in lines[-cap:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(_public_event(item))
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Studio GPU-second cost estimate (local; not a Modal invoice)",
    )
    parser.add_argument("--recipe", "--catalog", dest="recipe", default="")
    parser.add_argument("--gpu", default="")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--keep-gpu", action="store_true")
    parser.add_argument("--trace", action="store_true", help="print recent run traces")
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.trace:
        from studio.trace import recent_runs

        json.dump(recent_runs(args.limit), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    if not args.recipe and not args.gpu:
        print("need --recipe and/or --gpu", file=sys.stderr)
        return 2
    payload = predict(
        recipe=args.recipe,
        gpu=args.gpu,
        count=args.count,
        keep_gpu=args.keep_gpu,
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
