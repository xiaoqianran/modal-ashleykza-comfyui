#!/usr/bin/env python3
"""Build a single Studio.exe. Run on windows-latest CI."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.12.10"
EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
MODAL_PIP_SPEC = "modal[api-proxy-support]"
PACKAGES = ("catalog", "studio")
MODULES = (
    "base_nodes.py",
    "comfy_engine.py",
    "comfyui_modal.py",
    "hydrate_modal.py",
    "modal_config.py",
    "recipes.py",
    "sparse_3d_runtime.py",
    "storage.py",
    "workflow_queue.py",
    "workflow_resolver.py",
)
README = """Studio
======

只需要这一个 Studio.exe。双击即可，浏览器打开 http://127.0.0.1:8787

第一次会把运行时写到 %LOCALAPPDATA%\\ComfyStudio，下载目录里始终只有 exe。
图跑在 Modal 云上。本机要联网、Modal 账号、Hugging Face token。

走代理：在系统或用户环境变量里设 HTTPS_PROXY / ALL_PROXY（Modal CLI 已带 api-proxy-support）。
不想走代理：设 MODAL_DISABLE_API_PROXY=1。

workflow 模式需要本机 Chrome 或 Edge（graphToPrompt）。
mode=graph 的 Z-Image / Z-Image-Turbo 不需要。生成结束默认停 GPU。
"""


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"download {url}", flush=True)
    with urllib.request.urlopen(url) as response, dest.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _copy_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".studio", ".env"),
    )


def write_stamp(payload_dir: Path) -> Path:
    stamp = os.environ.get("GITHUB_SHA") or os.environ.get("STUDIO_PAYLOAD_STAMP") or "dev"
    path = payload_dir / "payload.stamp"
    path.write_text(stamp.strip() + "\n", encoding="utf-8")
    return path


def prepare_embed(python_dir: Path) -> Path:
    if python_dir.exists():
        shutil.rmtree(python_dir)
    python_dir.mkdir(parents=True)
    archive = python_dir / "embed.zip"
    _download(EMBED_URL, archive)
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(python_dir)
    archive.unlink()
    pth = next(python_dir.glob("python*._pth"))
    lines = [line.rstrip() for line in pth.read_text(encoding="utf-8").splitlines()]
    rewritten: list[str] = []
    seen_site = False
    for line in lines:
        if line.lstrip().startswith("#") and "import site" in line:
            rewritten.append("import site")
            seen_site = True
            continue
        if line.strip() == "import site":
            seen_site = True
        rewritten.append(line)
    if not seen_site:
        rewritten.append("import site")
    if "Lib\\site-packages" not in rewritten and "Lib/site-packages" not in rewritten:
        rewritten.insert(1, "Lib\\site-packages")
    pth.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    (python_dir / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    return python_dir / "python.exe"


def slim_embed(python_dir: Path) -> None:
    python_exe = python_dir / "python.exe"
    subprocess.call(
        [
            str(python_exe),
            "-m",
            "pip",
            "uninstall",
            "-y",
            "pip",
            "setuptools",
            "wheel",
        ]
    )
    for name in ("get-pip.py",):
        path = python_dir / name
        if path.is_file():
            path.unlink()
    scripts = python_dir / "Scripts"
    if scripts.is_dir():
        for path in scripts.iterdir():
            lowered = path.name.lower()
            if lowered.startswith(("pip", "wheel", "easy_install")):
                path.unlink(missing_ok=True)
    for cache in list(python_dir.rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)


def install_deps(python_exe: Path) -> None:
    get_pip = python_exe.parent / "get-pip.py"
    _download(GET_PIP_URL, get_pip)
    subprocess.check_call([str(python_exe), str(get_pip), "--no-warn-script-location"])
    subprocess.check_call(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--no-warn-script-location",
            MODAL_PIP_SPEC,
            "playwright",
        ]
    )
    slim_embed(python_exe.parent)


def copy_app(app_dir: Path) -> None:
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir(parents=True)
    for name in MODULES:
        shutil.copy2(ROOT / name, app_dir / name)
    for package in PACKAGES:
        _copy_tree(ROOT / package, app_dir / package)
    examples = app_dir / "examples"
    examples.mkdir()
    for path in sorted((ROOT / "examples").glob("*.json")):
        shutil.copy2(path, examples / path.name)
    (app_dir / "README.txt").write_text(README, encoding="utf-8")


def build_launcher(payload_dir: Path, dist_dir: Path) -> Path:
    python = payload_dir / "python"
    app = payload_dir / "app"
    stamp = payload_dir / "payload.stamp"
    sep = os.pathsep
    dist_dir.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--console",
            "--name",
            "Studio",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(ROOT / "build" / "studio-launcher"),
            "--specpath",
            str(ROOT / "build"),
            "--add-data",
            f"{python}{sep}python",
            "--add-data",
            f"{app}{sep}app",
            "--add-data",
            f"{stamp}{sep}payload.stamp",
            str(ROOT / "packaging" / "windows_launcher.py"),
        ]
    )
    return dist_dir / "Studio.exe"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "dist" / "payload"))
    parser.add_argument("--skip-embed", action="store_true")
    parser.add_argument("--skip-launcher", action="store_true")
    args = parser.parse_args(argv)
    payload_dir = Path(args.out).resolve()
    payload_dir.mkdir(parents=True, exist_ok=True)
    copy_app(payload_dir / "app")
    write_stamp(payload_dir)
    if not args.skip_embed:
        python_exe = prepare_embed(payload_dir / "python")
        install_deps(python_exe)
    if not args.skip_launcher:
        exe = build_launcher(payload_dir, payload_dir.parent)
        print(f"exe {exe} bytes={exe.stat().st_size}", flush=True)
        return 0
    print(f"payload {payload_dir}", flush=True)
    return 0


if __name__ == "__main__":
    if os.name != "nt" and "--allow-non-windows" not in sys.argv:
        raise SystemExit("build_windows.py is meant for windows-latest CI")
    raise SystemExit(main([item for item in sys.argv[1:] if item != "--allow-non-windows"]))
