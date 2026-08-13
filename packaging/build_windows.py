#!/usr/bin/env python3
"""Assemble the Windows portable Studio folder. Run on windows-latest CI."""

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
PACKAGES = ("catalog", "studio")
MODULES = (
    "base_nodes.py",
    "comfy_engine.py",
    "comfyui_modal.py",
    "hydrate_modal.py",
    "modal_config.py",
    "recipes.py",
    "storage.py",
    "workflow_queue.py",
    "workflow_resolver.py",
)
README = """Studio（Windows 便携版）
========================

双击 Studio.exe。会打开浏览器 http://127.0.0.1:8787

本机不需要先装 Python / ComfyUI / 显卡。图跑在 Modal 云上。

第一次：
1. 在页面填 Modal Token（或事先 modal setup）和 HF_TOKEN，保存
2. 顶栏选配方（默认 Z-Image）
3. 准备权重 → 启动 GPU → 生成
4. 图生配方（Pixal3D / TripoSplat）把图片拖进页面再点生成

FLUX.2 / Qwen / Krea-2 / Pixal3D / TripoSplat 需要本机已安装 Chrome（或 Edge），
用来把官方工作流转成 API prompt。Z-Image 不需要。

密钥只写在解压目录 app/.studio.env，不会上传 Git。

不要把 GPU 挂着不管。生成结束默认会停卡。
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
            "--no-warn-script-location",
            "modal",
            "playwright",
        ]
    )


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


def build_launcher(out_dir: Path) -> None:
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
            str(out_dir),
            "--workpath",
            str(ROOT / "build" / "studio-launcher"),
            "--specpath",
            str(ROOT / "build"),
            str(ROOT / "packaging" / "windows_launcher.py"),
        ]
    )


def zip_bundle(out_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=out_dir.parent, base_dir=out_dir.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "dist" / "Studio"))
    parser.add_argument("--skip-embed", action="store_true")
    parser.add_argument("--skip-launcher", action="store_true")
    args = parser.parse_args(argv)
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    copy_app(out_dir / "app")
    (out_dir / "README.txt").write_text(README, encoding="utf-8")
    if not args.skip_embed:
        python_exe = prepare_embed(out_dir / "python")
        install_deps(python_exe)
    if not args.skip_launcher:
        build_launcher(out_dir)
    zip_path = out_dir.parent / "Studio-windows.zip"
    zip_bundle(out_dir, zip_path)
    print(f"bundle {out_dir}", flush=True)
    print(f"zip {zip_path} bytes={zip_path.stat().st_size}", flush=True)
    return 0


if __name__ == "__main__":
    if os.name != "nt" and "--allow-non-windows" not in sys.argv:
        raise SystemExit("build_windows.py is meant for windows-latest CI")
    raise SystemExit(main([item for item in sys.argv[1:] if item != "--allow-non-windows"]))
