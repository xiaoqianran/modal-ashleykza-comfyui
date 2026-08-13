from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from recipes import MODEL_DIRS, MODEL_PACKS, NODE_PACKS, ModelAsset, NodeRecipe, get_profile
from storage import (
    DEFAULT_STORAGE_ROOT,
    ensure_storage_layout,
    extra_model_paths_yaml,
    legacy_model_path,
    resolve_model_file,
    storage_model_path,
)
from workflow_resolver import validate_workflow_lock

LOCK_SCHEMA = 1


def _quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    display_cmd: list[str] | None = None,
) -> None:
    printable = " ".join(_quote(part) for part in (display_cmd or cmd))
    print(f"$ {printable}", flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


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


def ensure_workspace_layout(workspace: Path) -> None:
    for directory in (
        "custom_nodes",
        "input",
        "output",
        "user",
        "logs",
        "state",
        *(f"models/{name}" for name in MODEL_DIRS),
    ):
        (workspace / directory).mkdir(parents=True, exist_ok=True)


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
    """
    parsed = _parse_hf_url(asset.url)
    hf = shutil.which("hf") or shutil.which("huggingface-cli")
    if not parsed or not hf:
        raise RuntimeError("Hugging Face CLI/Xet downloader is unavailable for this URL.")

    repo_id, revision, file_path = parsed
    before = {p.resolve() for p in target_dir.rglob("*") if p.is_file()}
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
        str(target_dir),
    ]
    env = os.environ.copy()
    env.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
    _run(cmd, env=env)

    expected = target_dir / file_path
    if expected.exists() and expected.resolve() != target.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        expected.replace(target)
        parent = expected.parent
        while parent != target_dir and parent.exists():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    if not target.exists():
        after = [p for p in target_dir.rglob("*") if p.is_file() and p.resolve() not in before]
        after = [p for p in after if ".cache/huggingface" not in p.as_posix()]
        if len(after) == 1:
            after[0].replace(target)

    if not target.exists():
        raise RuntimeError(f"HF CLI completed but expected file was not found: {target}")


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
        url,
    ]
    display_cmd = [*cmd[:-1], redact_url(url)]
    _run(cmd, display_cmd=display_cmd)


def download_asset(asset: ModelAsset, target_dir: Path, *, lock_entry: dict | None = None) -> dict:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / asset_filename(asset)
    target.parent.mkdir(parents=True, exist_ok=True)

    if _is_asset_current(target, asset, lock_entry):
        print(f"[SKIP] {target}")
        return lock_entry or {}

    normalized = normalize_huggingface_url(asset.url)
    print(f"[DOWNLOAD] {redact_url(_with_civitai_token(normalized))}")
    print(f"           -> {target}")

    if _parse_hf_url(normalized):
        try:
            _download_with_hf_cli(asset, target_dir, target)
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            print(f"[WARN] HF Xet download failed ({exc}); falling back to aria2c.")
            _download_with_aria2(asset, target_dir, target)
    else:
        _download_with_aria2(asset, target_dir, target)

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
    filename = asset_filename(asset)
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
        download_asset(
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
    state_dir = storage_root / ".state"
    profile = get_profile(profile_name)
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
) -> dict:
    """Download every resolved workflow model into the Modal models Volume.

    The lock is produced locally and serialized into the CPU-only Modal Function,
    so arbitrary local workflow files never need to be mounted in a GPU container.
    """
    validate_workflow_lock(workflow_lock, require_resolved=True)
    workspace = Path(workspace)
    storage_root = ensure_storage_layout(storage_root)
    ensure_workspace_layout(workspace)
    state_dir = storage_root / ".state"
    state_lock = _load_lock(state_dir)
    workflow = workflow_lock.get("workflow", {})
    workflow_name = str(workflow.get("name", "workflow"))
    workflow_sha256 = str(workflow.get("sha256", ""))

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


def build_node_commands(node_pack_names: tuple[str, ...] | list[str]) -> list[str]:
    """Translate declarative node recipes into idempotent image-build shell commands."""
    recipes: list[NodeRecipe] = []
    seen_names: set[str] = set()

    for pack_name in node_pack_names:
        for recipe in NODE_PACKS[pack_name]:
            assert recipe.name
            if recipe.name in seen_names:
                continue
            seen_names.add(recipe.name)
            recipes.append(recipe)

    commands: list[str] = []
    for recipe in recipes:
        assert recipe.name
        qrepo = _quote(recipe.repo)
        qname = _quote(recipe.name)

        clone_flags = ["--depth=1"]
        if recipe.ref:
            clone_flags.extend(["--branch", _quote(recipe.ref)])
        if recipe.recursive:
            clone_flags.extend(["--recursive", "--shallow-submodules"])

        steps = [
            # Do not enable xtrace before secret handling: `set -x` would print
            # the expanded GITHUB_TOKEN in build logs.
            "set -eu",
            'if [ -n "${GITHUB_TOKEN:-}" ]; then printf \'%s\\n\' \'#!/bin/sh\' \'case "$1" in *Username*) echo x-access-token ;; *) echo "$GITHUB_TOKEN" ;; esac\' > /tmp/comfy-git-askpass && chmod 700 /tmp/comfy-git-askpass && export GIT_ASKPASS=/tmp/comfy-git-askpass GIT_TERMINAL_PROMPT=0; fi',
            "set -x",
            "mkdir -p /ComfyUI/custom_nodes",
            "cd /ComfyUI/custom_nodes",
            (
                f"if [ ! -d {qname} ]; then "
                f"git clone {' '.join(clone_flags)} {qrepo} {qname}; "
                f"fi"
            ),
            f"cd {qname}",
            'PY=/ComfyUI/venv/bin/python3; [ -x "$PY" ] || PY=/ComfyUI/venv/bin/python; '
            '[ -x "$PY" ] || PY=python3',
        ]

        for command in recipe.pre_commands:
            steps.append(command)

        for req in recipe.requirements:
            qreq = _quote(req)
            steps.append(
                f'if [ -f {qreq} ]; then "$PY" -m pip install --no-cache-dir -r {qreq}; fi'
            )

        if recipe.pip:
            steps.append(
                '"$PY" -m pip install --no-cache-dir '
                + " ".join(_quote(package) for package in recipe.pip)
            )

        for command in recipe.commands:
            steps.append(command)

        steps.append("rm -f /tmp/comfy-git-askpass")
        commands.append("; ".join(steps))

    return commands


def build_registry_node_commands(
    custom_nodes: Iterable[Mapping[str, Any]],
    *,
    comfy_cli_version: str | None = "1.16.0",
) -> list[str]:
    """Install workflow-declared CNR nodes in CPU-backed Image build layers."""
    nodes = list(custom_nodes)
    if not nodes:
        return []

    comfy_cli_spec = f"comfy-cli=={comfy_cli_version}" if comfy_cli_version else "comfy-cli"
    bootstrap = "; ".join(
        (
            "set -eux",
            'PY=/ComfyUI/venv/bin/python3; [ -x "$PY" ] || PY=/ComfyUI/venv/bin/python; '
            '[ -x "$PY" ] || PY=python3',
            f'"$PY" -m pip install --no-cache-dir {_quote(comfy_cli_spec)}',
        )
    )
    commands = [bootstrap]

    for node in nodes:
        node_id = str(node["id"])
        version = node.get("version")
        install = [
            'COMFY=/ComfyUI/venv/bin/comfy; [ -x "$COMFY" ] || COMFY=comfy',
            f'"$COMFY" --workspace=/ComfyUI node registry-install {_quote(node_id)}',
        ]
        if version:
            install[-1] += f" --version {_quote(str(version))}"
        qnode = _quote(node_id)
        commands.append(
            "; ".join(
                (
                    "set -eux",
                    "mkdir -p /ComfyUI/custom_nodes",
                    (
                        "if ! find /ComfyUI/custom_nodes -mindepth 1 -maxdepth 1 "
                        f"-type d -iname {qnode} -print -quit | grep -q .; then "
                        + "; ".join(install)
                        + "; fi"
                    ),
                )
            )
        )
    return commands


def write_extra_model_paths(
    comfy_root: str | Path,
    workspace: str | Path,
    storage_root: str | Path = DEFAULT_STORAGE_ROOT,
) -> Path:
    """Write ComfyUI extra_model_paths.yaml with Volume dirs mapped 1:1."""
    path = Path(comfy_root) / "extra_model_paths.yaml"
    path.write_text(
        extra_model_paths_yaml(storage_root=storage_root, workspace=workspace),
        encoding="utf-8",
    )
    return path


def _replace_with_symlink(link_path: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if link_path.is_symlink():
        if link_path.resolve() == target.resolve():
            return
        link_path.unlink()
    elif link_path.exists():
        backup = link_path.with_name(link_path.name + ".image-bak")
        if backup.exists():
            if link_path.is_dir():
                shutil.rmtree(link_path)
            else:
                link_path.unlink()
        else:
            link_path.rename(backup)
    link_path.symlink_to(target, target_is_directory=True)


def prepare_runtime(
    comfy_root: str | Path = "/ComfyUI",
    workspace: str | Path = "/workspace",
    storage_root: str | Path = DEFAULT_STORAGE_ROOT,
) -> None:
    comfy_root = Path(comfy_root)
    workspace = Path(workspace)
    storage_root = Path(storage_root)

    if not (comfy_root / "main.py").exists():
        raise RuntimeError(f"ComfyUI main.py not found under {comfy_root}")

    ensure_workspace_layout(workspace)
    ensure_storage_layout(storage_root)
    write_extra_model_paths(comfy_root, workspace, storage_root)

    for name in ("input", "output", "user"):
        _replace_with_symlink(comfy_root / name, workspace / name)

    write_optional_node_configs(comfy_root, workspace)


def write_optional_node_configs(comfy_root: Path, workspace: Path) -> None:
    """Materialize secret-backed node config without storing credentials in Git."""
    candidates = (
        comfy_root / "custom_nodes" / "ComfyUI-OllamaGemini",
        workspace / "custom_nodes" / "ComfyUI-OllamaGemini",
    )
    node = next((candidate for candidate in candidates if candidate.exists()), None)
    if node is None:
        return

    values = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
        "OLLAMA_URL": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        "QWEN_API_KEY": os.environ.get("QWEN_API_KEY", ""),
    }
    if not any(values[key] for key in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "QWEN_API_KEY")):
        return

    config_path = node / "config.json"
    config_path.write_text(
        json.dumps(values, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    print("Wrote secret-backed ComfyUI-OllamaGemini/config.json")


def start_comfyui(
    *,
    profile_name: str,
    comfy_root: str | Path = "/ComfyUI",
    workspace: str | Path = "/workspace",
    port: int = 3001,
    extra_args: tuple[str, ...] | list[str] = (),
) -> subprocess.Popen:
    comfy_root = Path(comfy_root)
    workspace = Path(workspace)
    profile = get_profile(profile_name)

    python = comfy_root / "venv" / "bin" / "python3"
    if not python.exists():
        python = comfy_root / "venv" / "bin" / "python"
    if not python.exists():
        python = Path("python3")

    cmd = [
        str(python),
        str(comfy_root / "main.py"),
        "--listen", "0.0.0.0",
        "--port", str(port),
        *profile.comfy_args,
        *extra_args,
    ]

    log_path = workspace / "logs" / "comfyui.log"
    log = log_path.open("a", buffering=1)
    print("Starting:", " ".join(shlex.quote(arg) for arg in cmd))
    process = subprocess.Popen(
        cmd,
        cwd=str(comfy_root),
        stdout=log,
        stderr=log,
    )
    time.sleep(2)
    if process.poll() is not None:
        tail = ""
        try:
            tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:])
        except OSError:
            pass
        raise RuntimeError(f"ComfyUI exited during startup (code={process.returncode}).\n{tail}")
    return process


def wait_comfyui_ready(*, port: int, timeout: int = 600) -> None:
    """Block until the local ComfyUI HTTP server answers /system_stats."""
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/system_stats"
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=5)
            print(f"ComfyUI ready on :{port}", flush=True)
            return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(1)
    raise RuntimeError(f"ComfyUI did not become ready on :{port} within {timeout}s")
