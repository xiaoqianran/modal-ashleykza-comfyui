"""Download / verify workflow and legacy-profile weights into Modal Storage.

Patched helpers (``_run``, ``download_asset``, ``_download_with_*``) are looked
up on ``comfy_engine`` so existing unit tests keep working.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import threading
import time
import zipfile
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from recipes import MODEL_PACKS, ModelAsset
from storage import (
    DEFAULT_STORAGE_ROOT,
    canonical_relpath,
    download_target,
    ensure_storage_layout,
    ensure_workspace_layout,
    legacy_model_path,
    repair_storage_layout,
    repair_workspace_layout,
    resolve_model_file,
    storage_model_path,
)
from workflow_resolver import validate_workflow_lock


def _eng():
    import comfy_engine

    return comfy_engine


LOCK_SCHEMA = 1
LAUNCH_STATE_SCHEMA = 1
LAUNCH_STATE_FILE = "launch.json"
WORKFLOW_LOCK_STATE_FILE = "workflow.lock.json"

def normalize_huggingface_url(url: str) -> str:
    parsed = urlparse(url)
    if "huggingface.co" in parsed.netloc and "/blob/" in parsed.path:
        parsed = parsed._replace(path=parsed.path.replace("/blob/", "/resolve/"))
    return urlunparse(parsed)


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key in tuple(query):
        if key.lower() in {
            "access_token",
            "api_key",
            "apikey",
            "auth",
            "authorization",
            "key",
            "token",
        }:
            query[key] = ["***"]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _with_civitai_token(url: str) -> str:
    token = os.environ.get("CIVITAI_TOKEN", "").strip()
    if not token or "civitai.com" not in url:
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.setdefault("token", [token])
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def asset_filename(asset: ModelAsset) -> str:
    if asset.filename:
        return asset.filename
    parsed = urlparse(normalize_huggingface_url(asset.url))
    name = Path(parsed.path).name
    return name or "download"


def _sha256(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block_size):
            h.update(chunk)
    return h.hexdigest()


def _safe_member_path(base: Path, name: str) -> Path:
    target = (base / name).resolve()
    base = base.resolve()
    if os.path.commonpath([str(base), str(target)]) != str(base):
        raise RuntimeError(f"Unsafe archive member path: {name}")
    return target


def _extract_archive(path: Path) -> None:
    lower = path.name.lower()
    target_dir = path.parent

    if lower.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                _safe_member_path(target_dir, item.filename)
                unix_mode = item.external_attr >> 16
                if unix_mode and (unix_mode & 0o170000) == 0o120000:
                    raise RuntimeError(f"Archive symlinks are not allowed: {item.filename}")
            archive.extractall(target_dir)
        path.unlink()
        return

    tar_suffixes = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
    if lower.endswith(tar_suffixes):
        with tarfile.open(path, "r:*") as archive:
            for item in archive.getmembers():
                _safe_member_path(target_dir, item.name)
            archive.extractall(target_dir, filter="data")
        path.unlink()


def _lock_path(state_dir: Path) -> Path:
    return state_dir / "comfy.lock.json"


def _load_lock(state_dir: Path) -> dict:
    lock_path = _lock_path(state_dir)
    if not lock_path.exists():
        return {"schema": LOCK_SCHEMA, "assets": {}}
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema": LOCK_SCHEMA, "assets": {}}
    if data.get("schema") != LOCK_SCHEMA:
        return {"schema": LOCK_SCHEMA, "assets": {}}
    data.setdefault("assets", {})
    return data


def _save_lock(state_dir: Path, lock: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = _lock_path(state_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(lock, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def persist_launch_state(
    storage_root: str | Path,
    *,
    mode: str,
    profile: str = "base",
    workflow: str = "",
    lock_source: str = "",
    install_lock_nodes: bool = True,
    workflow_lock: Mapping[str, Any] | None = None,
) -> dict:
    """Write the active workflow/profile onto the models Volume.

    GPU start reads this instead of baking the lock into the Image, so every
    workflow shares the same cached Image layers.
    """
    storage_root = ensure_storage_layout(storage_root)
    state_dir = storage_root / ".state"
    lock_payload = dict(workflow_lock) if workflow_lock is not None else None
    if lock_payload is not None:
        validate_workflow_lock(lock_payload, require_resolved=True)
        _write_json(state_dir / WORKFLOW_LOCK_STATE_FILE, lock_payload)
    else:
        stale = state_dir / WORKFLOW_LOCK_STATE_FILE
        if stale.exists():
            stale.unlink()

    payload = {
        "schema": LAUNCH_STATE_SCHEMA,
        "mode": mode,
        "profile": profile or "base",
        "workflow": workflow,
        "lock_source": lock_source,
        "install_lock_nodes": bool(install_lock_nodes),
        "workflow_lock": lock_payload,
    }
    _write_json(state_dir / LAUNCH_STATE_FILE, payload)
    return payload


def load_launch_state(storage_root: str | Path) -> dict | None:
    path = Path(storage_root) / ".state" / LAUNCH_STATE_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def launch_fingerprint(
    launch: Mapping[str, Any] | None,
    *,
    profile_name: str,
    install_lock_nodes: bool,
) -> str:
    """Identity of Volume launch state that requires a ComfyUI process restart.

    Model files can appear after ``Volume.reload()`` without restarting.
    Custom nodes and profile ``comfy_args`` cannot.
    """
    payload = launch or {}
    lock = payload.get("workflow_lock") if isinstance(payload.get("workflow_lock"), Mapping) else {}
    nodes = []
    for node in lock.get("custom_nodes") or ():
        if isinstance(node, Mapping) and node.get("id"):
            nodes.append(f"{node.get('id')}@{node.get('version') or ''}")
    return json.dumps(
        {
            "custom_nodes": sorted(nodes),
            "install_lock_nodes": bool(
                payload.get("install_lock_nodes", install_lock_nodes)
            ),
            "profile": str(payload.get("profile") or profile_name or "base"),
        },
        sort_keys=True,
    )


def _asset_lock_entry(lock: Mapping[str, Any], category: str, filename: str) -> dict | None:
    assets = lock.get("assets", {})
    return assets.get(f"{category}/{filename}") or assets.get(f"models/{category}/{filename}")


def _promote_legacy_if_needed(legacy: Path, primary: Path) -> bool:
    """Copy a previously downloaded workspace model into Modal Storage."""
    if primary.is_file() and primary.stat().st_size > 0:
        return False
    if not (legacy.is_file() and legacy.stat().st_size > 0):
        return False
    primary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy, primary)
    print(f"[PROMOTE] {legacy} -> {primary}", flush=True)
    return True


def output_manifest(output_dir: str | Path) -> tuple[tuple[str, int, int], ...]:
    """Filename, mtime_ns, size for every file under ComfyUI ``output/``."""
    root = Path(output_dir)
    if not root.is_dir():
        return ()
    entries = []
    for path in root.rglob("*"):
        if path.is_file():
            stat = path.stat()
            entries.append(
                (str(path.relative_to(root)), int(stat.st_mtime_ns), int(stat.st_size))
            )
    return tuple(sorted(entries))


def _is_asset_current(path: Path, asset: ModelAsset, lock_entry: dict | None) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    if asset.sha256:
        return _sha256(path).lower() == asset.sha256.lower()
    if not lock_entry:
        return False
    return (
        lock_entry.get("url") == normalize_huggingface_url(asset.url)
        and lock_entry.get("size") == path.stat().st_size
    )


def _parse_hf_url(url: str) -> tuple[str, str, str] | None:
    """Return repo_id, revision, file path for a huggingface.co /resolve/ URL."""
    parsed = urlparse(normalize_huggingface_url(url))
    if "huggingface.co" not in parsed.netloc:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 4:
        return None

    repo_id = "/".join(parts[:2])
    try:
        marker = parts.index("resolve", 2)
    except ValueError:
        return None

    if marker + 1 >= len(parts):
        return None
    revision = parts[marker + 1]
    file_path = "/".join(parts[marker + 2 :])
    if not file_path:
        return None
    return repo_id, revision, file_path


def _download_with_hf_cli(asset: ModelAsset, target_dir: Path, target: Path) -> None:
    """Download a Hugging Face asset through huggingface_hub/hf_xet.

    Modern huggingface_hub installs hf_xet automatically. The Modal sync Image
    enables HF_XET_HIGH_PERFORMANCE=1, so this is the preferred path for HF.

    Downloads into /tmp first. ``--local-dir <category>`` plus a repo path of
    ``<category>/<file>`` would nest directories on the Volume and break.
    """
    parsed = _eng()._parse_hf_url(asset.url)
    hf = shutil.which("hf") or shutil.which("huggingface-cli")
    if not parsed or not hf:
        raise RuntimeError("Hugging Face CLI/Xet downloader is unavailable for this URL.")

    repo_id, revision, file_path = parsed
    tmp_root = Path("/tmp/hf-download") / hashlib.sha256(
        f"{repo_id}:{revision}:{file_path}".encode()
    ).hexdigest()[:16]
    if tmp_root.exists():
        shutil.rmtree(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        hf,
        "download",
        repo_id,
        file_path,
        "--revision",
        revision,
        "--repo-type",
        "model",
        "--local-dir",
        str(tmp_root),
    ]
    env = os.environ.copy()
    env.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
    token = (env.get("HF_TOKEN") or env.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    if token:
        env.setdefault("HF_TOKEN", token)
        env.setdefault("HUGGING_FACE_HUB_TOKEN", token)
    _eng()._run(cmd, env=env)

    expected = tmp_root / file_path
    if not expected.is_file():
        named = tmp_root / Path(file_path).name
        if named.is_file():
            expected = named
        else:
            matches = [
                path
                for path in tmp_root.rglob("*")
                if path.is_file() and path.name == Path(file_path).name
                and ".cache" not in path.parts
            ]
            if len(matches) != 1:
                raise RuntimeError(f"HF CLI completed but expected file was not found: {target}")
            expected = matches[0]

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    shutil.move(str(expected), str(target))
    shutil.rmtree(tmp_root, ignore_errors=True)

    if not target.exists():
        raise RuntimeError(f"HF CLI completed but expected file was not found: {target}")


def _hf_auth_header() -> str | None:
    token = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip()
    if not token:
        return None
    return f"Authorization: Bearer {token}"


def _download_with_aria2(asset: ModelAsset, target_dir: Path, target: Path) -> None:
    """Fast generic HTTP downloader used for Civitai and other direct URLs."""
    url = _with_civitai_token(normalize_huggingface_url(asset.url))
    aria = shutil.which("aria2c")
    if not aria:
        raise RuntimeError("aria2c is not installed in the sync image.")

    cmd = [
        aria,
        "-x", "16",
        "-s", "16",
        "-c",
        "-k", "1M",
        "--file-allocation=none",
        "--summary-interval=1",
        "--console-log-level=notice",
        "-d", str(target.parent),
        "-o", target.name,
    ]
    header = _hf_auth_header() if "huggingface.co" in url else None
    if header:
        cmd.extend(["--header", header])
    cmd.append(url)
    display_cmd = list(cmd)
    if header:
        display_cmd[display_cmd.index(header)] = "Authorization: Bearer ***"
    display_cmd[-1] = redact_url(url)
    _eng()._run(cmd, display_cmd=display_cmd)


def download_asset(asset: ModelAsset, target_dir: Path, *, lock_entry: dict | None = None) -> dict:
    target = download_target(target_dir, asset_filename(asset))
    target.parent.mkdir(parents=True, exist_ok=True)

    if _is_asset_current(target, asset, lock_entry):
        print(f"[SKIP] {target}")
        return lock_entry or {}

    normalized = normalize_huggingface_url(asset.url)
    print(f"[DOWNLOAD] {redact_url(_with_civitai_token(normalized))}")
    print(f"           -> {target}")

    if _eng()._parse_hf_url(normalized):
        try:
            _eng()._download_with_hf_cli(asset, target_dir, target)
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            print(f"[WARN] HF Xet download failed ({exc}); falling back to aria2c.")
            _eng()._download_with_aria2(asset, target_dir, target)
    else:
        _eng()._download_with_aria2(asset, target_dir, target)

    if not target.exists() or target.stat().st_size <= 0:
        raise RuntimeError(f"Download did not produce a non-empty file: {target}")

    if asset.sha256:
        actual = _sha256(target)
        if actual.lower() != asset.sha256.lower():
            raise RuntimeError(
                f"SHA256 mismatch for {target.name}: expected {asset.sha256}, got {actual}"
            )

    if asset.extract:
        _extract_archive(target)

    return {
        "url": normalized,
        "path": str(target),
        "size": target.stat().st_size if target.exists() else None,
        "sha256": asset.sha256,
        "synced_at": int(time.time()),
    }


def _hydrate_one_asset(
    asset: ModelAsset,
    category: str,
    *,
    workspace: Path,
    storage_root: Path,
    lock_entry: dict | None,
) -> tuple[dict, str]:
    filename = canonical_relpath(asset_filename(asset), category=category)
    asset = ModelAsset(
        url=asset.url,
        filename=filename,
        sha256=asset.sha256,
        extract=asset.extract,
    )
    primary = storage_model_path(storage_root, category, filename)
    legacy = legacy_model_path(workspace, category, filename)
    promoted = _promote_legacy_if_needed(legacy, primary)
    if promoted and not lock_entry:
        lock_entry = {
            "url": normalize_huggingface_url(asset.url),
            "size": primary.stat().st_size,
        }
    existed = _is_asset_current(primary, asset, lock_entry)
    new_entry = dict(
        _eng().download_asset(
            asset,
            storage_root / category,
            lock_entry=lock_entry,
        )
    )
    new_entry["path"] = str(primary)
    if existed and promoted:
        status = "promote"
    elif existed:
        status = "skip"
    else:
        status = "download"
    return new_entry, status


def _hydrate_assets_parallel(
    jobs: list[tuple[str, str, ModelAsset, dict]],
    *,
    workspace: Path,
    storage_root: Path,
    state_dir: Path,
    lock: dict,
    workers: int,
) -> dict[str, int]:
    """Download independent model files concurrently into Modal Storage.

    ``jobs`` items are ``(rel_key, category, asset, extra_metadata)``.
    Extra metadata is merged into the persisted lock entry after download.
    """
    counts = {"download": 0, "skip": 0, "promote": 0}
    guard = threading.Lock()

    def run_job(rel_key: str, category: str, asset: ModelAsset, extra: dict) -> None:
        entry = _asset_lock_entry(lock, category, asset_filename(asset))
        new_entry, status = _hydrate_one_asset(
            asset,
            category,
            workspace=workspace,
            storage_root=storage_root,
            lock_entry=entry,
        )
        with guard:
            previous = lock["assets"].get(rel_key, {})
            packs = set(previous.get("packs", [])) | set(extra.get("packs", []))
            workflows = set(previous.get("workflows", [])) | set(extra.get("workflows", []))
            if packs:
                new_entry["packs"] = sorted(packs)
            if workflows:
                new_entry["workflows"] = sorted(workflows)
            lock["assets"][rel_key] = new_entry
            _save_lock(state_dir, lock)
            counts[status] += 1

    worker_count = max(1, min(workers, len(jobs)))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(run_job, rel_key, category, asset, extra)
            for rel_key, category, asset, extra in jobs
        ]
        for future in as_completed(futures):
            future.result()
    return counts


def sync_profile_models(
    profile_name: str,
    workspace: str | Path = "/workspace",
    *,
    storage_root: str | Path = DEFAULT_STORAGE_ROOT,
    workers: int = 4,
) -> dict:
    workspace = Path(workspace)
    storage_root = ensure_storage_layout(storage_root)
    ensure_workspace_layout(workspace)
    repair_storage_layout(storage_root)
    repair_workspace_layout(workspace)
    state_dir = storage_root / ".state"
    profile = _eng().get_profile(profile_name)
    lock = _load_lock(state_dir)

    wanted: list[tuple[str, str, ModelAsset, dict]] = []
    seen: set[tuple[str, str]] = set()
    for pack_name in profile.model_packs:
        pack = MODEL_PACKS[pack_name]
        for category, assets in pack.items():
            for asset in assets:
                filename = asset_filename(asset)
                key = (category, filename)
                if key in seen:
                    continue
                seen.add(key)
                wanted.append(
                    (
                        f"{category}/{filename}",
                        category,
                        asset,
                        {"packs": [pack_name]},
                    )
                )

    persist_launch_state(
        storage_root,
        mode="profile",
        profile=profile_name,
        install_lock_nodes=False,
    )

    if not wanted:
        print(f"Profile {profile_name!r} has no model assets.")
        return {
            "profile": profile_name,
            "downloaded": 0,
            "skipped": 0,
            "promoted": 0,
            "total": 0,
            "storage_root": str(storage_root),
        }

    counts = _hydrate_assets_parallel(
        wanted,
        workspace=workspace,
        storage_root=storage_root,
        state_dir=state_dir,
        lock=lock,
        workers=workers,
    )
    return {
        "profile": profile_name,
        "downloaded": counts["download"],
        "skipped": counts["skip"],
        "promoted": counts["promote"],
        "total": len(wanted),
        "storage_root": str(storage_root),
    }


def sync_workflow_models(
    workflow_lock: Mapping[str, Any],
    workspace: str | Path = "/workspace",
    *,
    storage_root: str | Path = DEFAULT_STORAGE_ROOT,
    workers: int = 4,
    install_lock_nodes: bool = True,
    workflow_source: str = "",
    lock_source: str = "",
    profile_name: str = "base",
) -> dict:
    """Download every resolved workflow model into the Modal models Volume.

    The lock is produced locally and serialized into the CPU-only Modal Function,
    so arbitrary local workflow files never need to be mounted in a GPU container.
    The active lock is also written to Volume ``.state/`` so the GPU Image can
    stay workflow-agnostic.
    """
    validate_workflow_lock(workflow_lock, require_resolved=True)
    workspace = Path(workspace)
    storage_root = ensure_storage_layout(storage_root)
    ensure_workspace_layout(workspace)
    repair_storage_layout(storage_root)
    repair_workspace_layout(workspace)
    state_dir = storage_root / ".state"
    state_lock = _load_lock(state_dir)
    workflow = workflow_lock.get("workflow", {})
    workflow_name = str(workflow.get("name", "workflow"))
    workflow_sha256 = str(workflow.get("sha256", ""))
    persist_launch_state(
        storage_root,
        mode="workflow",
        profile=profile_name,
        workflow=workflow_source or workflow_name,
        lock_source=lock_source,
        install_lock_nodes=install_lock_nodes,
        workflow_lock=workflow_lock,
    )

    jobs: list[tuple[str, str, ModelAsset, dict]] = []
    for model in workflow_lock["models"]:
        category = model["category"]
        filename = model["filename"]
        jobs.append(
            (
                f"{category}/{filename}",
                category,
                ModelAsset(
                    url=model["url"],
                    filename=filename,
                    sha256=model.get("sha256"),
                ),
                {"workflows": [workflow_sha256 or workflow_name]},
            )
        )

    counts = {"download": 0, "skip": 0, "promote": 0}
    if jobs:
        counts = _hydrate_assets_parallel(
            jobs,
            workspace=workspace,
            storage_root=storage_root,
            state_dir=state_dir,
            lock=state_lock,
            workers=workers,
        )

    return {
        "workflow": workflow_name,
        "workflow_sha256": workflow_sha256,
        "synced": len(jobs),
        "downloaded": counts["download"],
        "skipped": counts["skip"],
        "promoted": counts["promote"],
        "total": len(workflow_lock["models"]),
        "storage_root": str(storage_root),
    }


def verify_workflow_models(
    workflow_lock: Mapping[str, Any],
    workspace: str | Path = "/workspace",
    *,
    storage_root: str | Path = DEFAULT_STORAGE_ROOT,
) -> dict:
    """Fail fast when a GPU runtime is missing CPU-prefetched workflow models."""
    validate_workflow_lock(workflow_lock, require_resolved=True)
    workspace = Path(workspace)
    storage_root = Path(storage_root)
    missing = []
    for model in workflow_lock["models"]:
        target = resolve_model_file(
            storage_root=storage_root,
            workspace=workspace,
            category=model["category"],
            filename=model["filename"],
        )
        if not target.is_file() or target.stat().st_size <= 0:
            missing.append(f"{model['category']}/{model['filename']}")
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            "Workflow models were not prefetched into Modal Storage "
            f"({storage_root}): {joined}. Run action=hydrate or "
            "action=workflow-sync before starting the GPU endpoint."
        )
    return {"verified": len(workflow_lock["models"]), "missing": []}


