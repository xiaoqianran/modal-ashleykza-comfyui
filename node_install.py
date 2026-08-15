"""CNR / GitHub node install onto the workspace Volume.

``_run`` / ``_comfy_python`` / ``_site_packages`` / ``_quote`` are looked up on
``comfy_engine`` so existing unit tests keep patching that module.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from comfy_env_contract import (
    SKIP_PACKAGES as NODE_REQS_SKIP_PACKAGES,
)
from recipes import NODE_PACKS, NodeRecipe
from sparse_3d_runtime import requirements_without_packages
from uv_runtime import pip_install_cmd, shell_resolve_uv


def _eng():
    import comfy_engine

    return comfy_engine


NODE_REQS_SITE_MARK = "node-reqs-site"
NODE_REQS_PTH_NAME = "comfy_node_reqs.pth"


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
        qrepo = _eng()._quote(recipe.repo)
        qname = _eng()._quote(recipe.name)

        clone_flags = ["--depth=1"]
        if recipe.ref:
            clone_flags.extend(["--branch", _eng()._quote(recipe.ref)])
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
            shell_resolve_uv(),
        ]

        for command in recipe.pre_commands:
            steps.append(command)

        for req in recipe.requirements:
            qreq = _eng()._quote(req)
            steps.append(
                f'if [ -f {qreq} ]; then "$UV" pip install --python "$PY" --no-cache -r {qreq}; fi'
            )

        if recipe.pip:
            steps.append(
                '"$UV" pip install --python "$PY" --no-cache '
                + " ".join(_eng()._quote(package) for package in recipe.pip)
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
    """Shell layers for optional Image-time CNR installs (tests / opt-in packs).

    Default GPU runtime does **not** use this. Workflow lock nodes go onto the
    workspace Volume via ``install_registry_nodes`` so the Image cache stays shared.
    """
    nodes = list(custom_nodes)
    if not nodes:
        return []

    comfy_cli_spec = f"comfy-cli=={comfy_cli_version}" if comfy_cli_version else "comfy-cli"
    bootstrap = "; ".join(
        (
            "set -eux",
            'PY=/ComfyUI/venv/bin/python3; [ -x "$PY" ] || PY=/ComfyUI/venv/bin/python; '
            '[ -x "$PY" ] || PY=python3',
            shell_resolve_uv(),
            f'"$UV" pip install --python "$PY" --no-cache {_eng()._quote(comfy_cli_spec)}',
        )
    )
    commands = [bootstrap]

    for node in nodes:
        node_id = str(node["id"])
        version = node.get("version")
        install = [
            'COMFY=/ComfyUI/venv/bin/comfy; [ -x "$COMFY" ] || COMFY=comfy',
            f'"$COMFY" --workspace=/ComfyUI node registry-install {_eng()._quote(node_id)}',
        ]
        if version:
            install[-1] += f" --version {_eng()._quote(str(version))}"
        qnode = _eng()._quote(node_id)
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


def _cnr_marker_path(marker_dir: Path, node_id: str) -> Path:
    safe_id = node_id.replace("/", "_")
    return marker_dir / safe_id


def _dir_names(path: Path) -> set[str]:
    if not path.is_dir():
        return set()
    return {item.name for item in path.iterdir() if item.is_dir() and not item.name.startswith(".")}


def _registry_install_one(node: Mapping[str, Any], *, comfy_root: Path) -> None:
    node_id = str(node["id"])
    version = node.get("version")
    comfy = comfy_root / "venv" / "bin" / "comfy"
    binary = str(comfy) if comfy.is_file() else "comfy"
    cmd = [binary, f"--workspace={comfy_root}", "node", "registry-install", node_id]
    if version:
        cmd.extend(["--version", str(version)])
    _eng()._run(cmd)


def install_registry_nodes(
    custom_nodes: Iterable[Mapping[str, Any]],
    *,
    comfy_root: str | Path = "/ComfyUI",
    custom_nodes_dir: str | Path = "/workspace/custom_nodes",
    marker_dir: str | Path | None = None,
    skip_existing: bool = True,
    installer: Callable[..., None] | None = None,
) -> list[str]:
    """Install CNR nodes into a Volume-backed ``custom_nodes`` directory.

    ``comfy node registry-install`` writes under ``<comfy_root>/custom_nodes``.
    Newly created folders are moved onto the Volume so they survive scaledown
    and do not bust the GPU Image cache. Existing Volume installs are skipped.
    ``requirements.txt`` is installed into ``<workspace>/.python/node-reqs``
    and reused across cold starts when the file hash matches.
    Markers live under ``/workspace/state/cnr`` so ComfyUI does not scan them.
    """
    nodes = list(custom_nodes)
    if not nodes:
        return []

    comfy_root = Path(comfy_root)
    image_custom = comfy_root / "custom_nodes"
    volume_custom = Path(custom_nodes_dir)
    volume_custom.mkdir(parents=True, exist_ok=True)
    markers = Path(marker_dir) if marker_dir is not None else volume_custom.parent / "state" / "cnr"
    markers.mkdir(parents=True, exist_ok=True)
    image_custom.mkdir(parents=True, exist_ok=True)
    run_install = installer or _registry_install_one

    installed: list[str] = []
    for node in nodes:
        node_id = str(node["id"])
        version = str(node.get("version") or "")
        marker = _cnr_marker_path(markers, node_id)
        previous = {}
        if marker.is_file():
            try:
                loaded = json.loads(marker.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                loaded = {}
            if isinstance(loaded, dict):
                previous = loaded
        url = str(node.get("url") or "").strip()
        if skip_existing and previous.get("version") == version and previous.get("dirs"):
            missing = [
                name
                for name in previous["dirs"]
                if not (volume_custom / str(name)).is_dir()
            ]
            if not missing:
                print(f"[SKIP] CNR {node_id}@{version} already on Volume", flush=True)
                # Clone lives on the Volume. requirements.txt is installed into
                # /workspace/.python/node-reqs and skipped when the hash matches.
                python = _eng()._comfy_python(comfy_root)
                reqs_changed = False
                for name in previous["dirs"]:
                    reqs_changed = (
                        _install_node_requirements(volume_custom / str(name), python)
                        or reqs_changed
                    )
                _remember_node_reqs(installed, reqs_changed)
                continue

        for name in previous.get("dirs") or ():
            stale = volume_custom / str(name)
            if stale.is_dir():
                shutil.rmtree(stale)

        if url:
            moved = _install_github_node(node, volume_custom)
        else:
            before = _dir_names(image_custom)
            run_install(node, comfy_root=comfy_root)
            new_names = sorted(_dir_names(image_custom) - before)
            moved = []
            for name in new_names:
                src = image_custom / name
                dest = volume_custom / name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                shutil.move(str(src), str(dest))
                moved.append(name)
        marker.write_text(
            json.dumps({"id": node_id, "version": version, "dirs": moved}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        python = _eng()._comfy_python(comfy_root)
        reqs_changed = False
        for name in moved:
            reqs_changed = (
                _install_node_requirements(volume_custom / str(name), python)
                or reqs_changed
            )
        kind = "git" if url else "CNR"
        print(
            f"[INSTALL] {kind} {node_id}@{version} -> {volume_custom} ({', '.join(moved) or 'no new dirs'})",
            flush=True,
        )
        installed.append(node_id)
        _remember_node_reqs(installed, reqs_changed)
    return installed


def _github_repo_dir_name(url: str) -> str:
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


def node_reqs_volume_path(workspace: str | Path) -> Path:
    return Path(workspace) / ".python" / "node-reqs"


def _node_req_marker(site_dir: Path, dest: Path) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in dest.name)
    return site_dir / ".markers" / f"{safe}.sha256"


def _hash_requirements(req_file: Path) -> str:
    return hashlib.sha256(req_file.read_bytes()).hexdigest()


def _remember_node_reqs(installed: list[str], changed: bool) -> None:
    if changed and NODE_REQS_SITE_MARK not in installed:
        installed.append(NODE_REQS_SITE_MARK)


def _link_node_reqs_site(python: str, site_dir: str | Path) -> bool:
    """Write a venv .pth so ComfyUI can import Volume-installed node deps.

    The .pth lives in the ephemeral Image venv; rewriting it is not a Volume change.
    Skip when ``python`` is not a real venv path (unit tests / hydrate CPU).
    """
    if not Path(python).is_file():
        return False
    purelib = _eng()._site_packages(python)
    if purelib is None:
        print("[NODE-REQS] cannot link Volume site (no site-packages)", flush=True)
        return False
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / ".markers").mkdir(parents=True, exist_ok=True)
    pth = purelib / NODE_REQS_PTH_NAME
    marker = f"{site_dir}\n"
    if not pth.is_file() or pth.read_text(encoding="utf-8") != marker:
        pth.write_text(marker, encoding="utf-8")
        print(f"[NODE-REQS] linked Volume site {site_dir}", flush=True)
    return False


def ensure_node_reqs_site(comfy_root: str | Path, workspace: str | Path) -> None:
    """Point the Image venv at Volume-backed CNR/GitHub node site-packages."""
    python = _eng()._comfy_python(Path(comfy_root))
    _link_node_reqs_site(python, node_reqs_volume_path(workspace))


def _install_node_requirements(
    dest: Path,
    python: str | None,
    *,
    site_dir: str | Path | None = None,
) -> bool:
    """Install ``requirements.txt`` onto the Volume site. Skip when the hash matches.

    Returns True if ``uv pip`` ran (Volume changed; caller should commit).
    """
    requirements = dest / "requirements.txt"
    if not python or not requirements.is_file():
        return False
    if site_dir is None:
        site_dir = dest.parent.parent / ".python" / "node-reqs"
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / ".markers").mkdir(parents=True, exist_ok=True)
    marker = _node_req_marker(site_dir, dest)
    digest = _hash_requirements(requirements)
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == digest:
        print(f"[SKIP] node reqs {dest.name} already on Volume", flush=True)
        return False
    filtered = requirements_without_packages(
        requirements.read_text(encoding="utf-8"),
        NODE_REQS_SKIP_PACKAGES,
    )
    req_file = requirements
    if filtered != requirements.read_text(encoding="utf-8"):
        req_file = site_dir / ".markers" / f"{dest.name}.requirements.txt"
        req_file.write_text(filtered, encoding="utf-8")
        print(f"[NODE-REQS] skip Image-only packages {sorted(NODE_REQS_SKIP_PACKAGES)}", flush=True)
    _eng()._run(pip_install_cmd(python, "-r", str(req_file), site_dir=site_dir))
    marker.write_text(digest + "\n", encoding="utf-8")
    print(f"[INSTALL] node reqs {dest.name} -> {site_dir}", flush=True)
    return True


def _install_github_node(
    node: Mapping[str, Any],
    volume_custom: Path,
) -> list[str]:
    url = str(node["url"]).strip()
    name = _github_repo_dir_name(url)
    dest = volume_custom / name
    if dest.exists():
        shutil.rmtree(dest)
    clone = ["git", "clone", "--depth=1"]
    version = str(node.get("version") or "").strip()
    if version:
        clone.extend(["--branch", version])
    clone.extend([url, str(dest)])
    try:
        _eng()._run(clone)
    except subprocess.CalledProcessError:
        if not version:
            raise
        print(f"[WARN] git clone --branch {version} failed; using default branch", flush=True)
        if dest.exists():
            shutil.rmtree(dest)
        _eng()._run(["git", "clone", "--depth=1", url, str(dest)])
    return [name]
