from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from recipes import MODEL_DIRS, MODEL_PACKS, NODE_PACKS, ModelAsset, NodeRecipe, get_profile

LOCK_SCHEMA = 1


def _quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("$ " + " ".join(_quote(part) for part in cmd), flush=True)
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
        if key.lower() in {"token", "auth", "authorization"}:
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
            archive.extractall(target_dir)
        path.unlink()
        return
    tar_suffixes = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
    if lower.endswith(tar_suffixes):
        with tarfile.open(path, "r:*") as archive:
            for item in archive.getmembers():
                _safe_member_path(target_dir, item.name)
            archive.extractall(target_dir)
        path.unlink()


def _load_lock(workspace: Path) -> dict:
    lock_path = workspace / "state" / "comfy.lock.json"
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


def _save_lock(workspace: Path, lock: dict) -> None:
    state = workspace / "state"
    state.mkdir(parents=True, exist_ok=True)
    path = state / "comfy.lock.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(lock, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def ensure_workspace_layout(workspace: Path) -> None:
    for directory in (
        "custom_nodes", "input", "output", "user", "logs", "state",
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
    return lock_entry.get("url") == normalize_huggingface_url(asset.url) and lock_entry.get("size") == path.stat().st_size


def _parse_hf_url(url: str) -> tuple[str, str, str] | None:
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
    file_path = "/".join(parts[marker + 2:])
    return (repo_id, revision, file_path) if file_path else None


def _download_with_hf_cli(asset: ModelAsset, target_dir: Path, target: Path) -> None:
    parsed = _parse_hf_url(asset.url)
    hf = shutil.which("hf") or shutil.which("huggingface-cli")
    if not parsed or not hf:
        raise RuntimeError("Hugging Face CLI fallback is unavailable for this URL.")
    repo_id, revision, file_path = parsed
    cmd = [
        hf, "download", repo_id, file_path,
        "--revision", revision,
        "--repo-type", "model",
        "--local-dir", str(target_dir),
    ]
    _run(cmd)
    expected = target_dir / file_path
    if expected.exists() and expected.resolve() != target.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        expected.replace(target)
    if not target.exists():
        raise RuntimeError(f"HF CLI completed but expected file was not found: {target}")


def download_asset(asset: ModelAsset, target_dir: Path, *, lock_entry: dict | None = None) -> dict:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / asset_filename(asset)
    if _is_asset_current(target, asset, lock_entry):
        print(f"[SKIP] {target}")
        return lock_entry or {}

    url = _with_civitai_token(normalize_huggingface_url(asset.url))
    print(f"[DOWNLOAD] {redact_url(url)}")
    print(f"           -> {target}")
    aria = shutil.which("aria2c")
    if not aria:
        raise RuntimeError("aria2c is not installed in the sync image.")

    cmd = [
        aria, "-x", "16", "-s", "16", "-c", "-k", "1M",
        "--file-allocation=none", "--summary-interval=1",
        "--console-log-level=notice", "-d", str(target_dir), "-o", target.name,
    ]
    hf_token = os.environ.get("HF_TOKEN", "").strip()
    if hf_token and "huggingface.co" in url:
        cmd.extend(["--header", f"Authorization: Bearer {hf_token}"])
    cmd.append(url)

    try:
        _run(cmd)
    except subprocess.CalledProcessError:
        if "huggingface.co" not in url:
            raise
        print("[WARN] aria2c failed; trying Hugging Face CLI fallback.")
        _download_with_hf_cli(asset, target_dir, target)

    if not target.exists() or target.stat().st_size <= 0:
        raise RuntimeError(f"Download did not produce a non-empty file: {target}")
    if asset.sha256:
        actual = _sha256(target)
        if actual.lower() != asset.sha256.lower():
            raise RuntimeError(f"SHA256 mismatch for {target.name}: expected {asset.sha256}, got {actual}")
    if asset.extract:
        _extract_archive(target)

    return {
        "url": normalize_huggingface_url(asset.url),
        "path": str(target),
        "size": target.stat().st_size if target.exists() else None,
        "sha256": asset.sha256,
        "synced_at": int(time.time()),
    }


def sync_profile_models(profile_name: str, workspace: str | Path = "/workspace") -> dict:
    workspace = Path(workspace)
    ensure_workspace_layout(workspace)
    profile = get_profile(profile_name)
    lock = _load_lock(workspace)

    wanted: list[tuple[str, str, ModelAsset]] = []
    seen: set[tuple[str, str]] = set()
    for pack_name in profile.model_packs:
        for category, assets in MODEL_PACKS[pack_name].items():
            for asset in assets:
                key = (category, asset_filename(asset))
                if key in seen:
                    continue
                seen.add(key)
                wanted.append((pack_name, category, asset))

    if not wanted:
        print(f"Profile {profile_name!r} has no model assets.")
        return {"profile": profile_name, "downloaded": 0, "total": 0}

    completed = 0
    for pack_name, category, asset in wanted:
        rel_key = f"models/{category}/{asset_filename(asset)}"
        entry = lock["assets"].get(rel_key)
        new_entry = download_asset(asset, workspace / "models" / category, lock_entry=entry)
        new_entry = dict(new_entry)
        new_entry["packs"] = sorted(set(new_entry.get("packs", [])) | {pack_name})
        lock["assets"][rel_key] = new_entry
        _save_lock(workspace, lock)
        completed += 1
    return {"profile": profile_name, "downloaded": completed, "total": len(wanted)}


def build_node_commands(node_pack_names: tuple[str, ...] | list[str]) -> list[str]:
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
        clone_flags = ["--depth=1"]
        if recipe.ref:
            clone_flags.extend(["--branch", _quote(recipe.ref)])
        if recipe.recursive:
            clone_flags.extend(["--recursive", "--shallow-submodules"])
        steps = [
            "set -eux",
            "mkdir -p /ComfyUI/custom_nodes",
            "cd /ComfyUI/custom_nodes",
            f"if [ ! -d {_quote(recipe.name)} ]; then git clone {' '.join(clone_flags)} {_quote(recipe.repo)} {_quote(recipe.name)}; fi",
            f"cd {_quote(recipe.name)}",
            'PY=/ComfyUI/venv/bin/python3; [ -x "$PY" ] || PY=/ComfyUI/venv/bin/python; [ -x "$PY" ] || PY=python3',
        ]
        steps.extend(recipe.pre_commands)
        for req in recipe.requirements:
            steps.append(f'if [ -f {_quote(req)} ]; then "$PY" -m pip install --no-cache-dir -r {_quote(req)}; fi')
        if recipe.pip:
            steps.append('"$PY" -m pip install --no-cache-dir ' + " ".join(_quote(package) for package in recipe.pip))
        steps.extend(recipe.commands)
        commands.append("; ".join(steps))
    return commands


def write_extra_model_paths(comfy_root: str | Path, workspace: str | Path) -> Path:
    comfy_root = Path(comfy_root)
    workspace = Path(workspace)
    lines = [
        "# Generated by comfy_engine.py. Edit recipes.py, not this file.",
        "modal_workspace:",
        f"    base_path: {workspace}",
        "    is_default: true",
    ]
    for name in MODEL_DIRS:
        lines.append(f"    {name}: models/{name}/")
    lines.append("    custom_nodes: custom_nodes/")
    lines.append("")
    path = comfy_root / "extra_model_paths.yaml"
    path.write_text("\n".join(lines), encoding="utf-8")
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


def prepare_runtime(comfy_root: str | Path = "/ComfyUI", workspace: str | Path = "/workspace") -> None:
    comfy_root = Path(comfy_root)
    workspace = Path(workspace)
    if not (comfy_root / "main.py").exists():
        raise RuntimeError(f"ComfyUI main.py not found under {comfy_root}")
    ensure_workspace_layout(workspace)
    write_extra_model_paths(comfy_root, workspace)
    for name in ("input", "output", "user"):
        _replace_with_symlink(comfy_root / name, workspace / name)
    write_optional_node_configs(comfy_root, workspace)


def write_optional_node_configs(comfy_root: Path, workspace: Path) -> None:
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
    (node / "config.json").write_text(json.dumps(values, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
        str(python), str(comfy_root / "main.py"),
        "--listen", "0.0.0.0", "--port", str(port),
        *profile.comfy_args, *extra_args,
    ]
    log_path = workspace / "logs" / "comfyui.log"
    log = log_path.open("a", buffering=1)
    print("Starting:", " ".join(shlex.quote(arg) for arg in cmd))
    process = subprocess.Popen(cmd, cwd=str(comfy_root), stdout=log, stderr=log)
    time.sleep(2)
    if process.poll() is not None:
        tail = ""
        try:
            tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:])
        except OSError:
            pass
        raise RuntimeError(f"ComfyUI exited during startup (code={process.returncode}).\n{tail}")
    return process
