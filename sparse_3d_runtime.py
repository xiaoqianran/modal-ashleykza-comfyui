"""Pixal3D / TRELLIS.2 CUDA wheels and Blackwell boot.

Download, CNR install, and ComfyUI process control stay in ``comfy_engine``.
Helpers such as ``_run`` / ``_python_text`` are looked up on that module so
existing unit-test patches keep working.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote


def _ce():
    import comfy_engine

    return comfy_engine


def _run(*args, **kwargs):
    return _ce()._run(*args, **kwargs)


def _python_text(*args, **kwargs):
    return _ce()._python_text(*args, **kwargs)


def _site_packages(*args, **kwargs):
    return _ce()._site_packages(*args, **kwargs)


def _comfy_python(*args, **kwargs):
    return _ce()._comfy_python(*args, **kwargs)


def _module_available(*args, **kwargs):
    return _ce()._module_available(*args, **kwargs)


def _module_import_error(*args, **kwargs):
    return _ce()._module_import_error(*args, **kwargs)


NATTEN_WHEEL_INDEX = "https://whl.natten.org"
NATTEN_DEFAULT_VERSION = "0.21.6"
FLASH_ATTN_TORCH211_WHEEL = (
    "https://github.com/lesj0610/flash-attention/releases/download/"
    "v2.8.3-cu12-torch2.11/"
    "flash_attn-2.8.3%2Bcu12torch2.11cxx11abiTRUE-cp{py}-cp{py}-linux_x86_64.whl"
)
CUDA_WHEEL_RELEASE = "https://github.com/PozzettiAndrea/cuda-wheels/releases/download"
# Ashley 0.32.0: CPython 3.12 + torch 2.11.0+cu128. visualbruno Torch2110 Linux
# wheels are cp313 only; these match cp312.
SPARSE_3D_WHEEL_FILES: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        "flex_gemm",
        ("flex_gemm_ap", "flex_gemm"),
        "flex_gemm_ap-latest",
        "flex_gemm_ap-1.0.0+cu128torch2.11-cp312-cp312-manylinux_2_34_x86_64.manylinux_2_35_x86_64.whl",
    ),
    (
        "cumesh",
        ("cumesh_vb", "cumesh"),
        "cumesh_vb-latest",
        "cumesh_vb-1.0+cu128torch2.11-cp312-cp312-manylinux_2_35_x86_64.whl",
    ),
    (
        "o_voxel",
        ("o_voxel_vb_ap", "o_voxel"),
        "o_voxel_vb_ap-latest",
        "o_voxel_vb_ap-0.0.1+cu128torch2.11-cp312-cp312-manylinux_2_34_x86_64.manylinux_2_35_x86_64.whl",
    ),
)
DRTK_WHEEL_FILE: tuple[str, tuple[str, ...], str, str] = (
    "drtk",
    ("drtk",),
    "drtk-latest",
    "drtk-0.1.0+cu128torch2.11-cp312-cp312-manylinux_2_34_x86_64.manylinux_2_35_x86_64.whl",
)
TRELLIS2_WHEEL_FILES: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        "nvdiffrast",
        ("nvdiffrast",),
        "nvdiffrast-latest",
        "nvdiffrast-0.4.0+cu128torch2.11-cp312-cp312-manylinux_2_34_x86_64.manylinux_2_35_x86_64.whl",
    ),
    (
        "nvdiffrec_render",
        ("nvdiffrec_render",),
        "nvdiffrec_render-latest",
        "nvdiffrec_render-0.0.1+cu128torch2.11-cp312-cp312-manylinux_2_34_x86_64.manylinux_2_35_x86_64.whl",
    ),
)
# CUDA wheels are installed with --no-deps so pip cannot replace Ashley's torch.
# Remaining Requires-Dist: (pip name, import name). No torch / triton / torchvision.
SPARSE_3D_WHEEL_PY_DEPS: tuple[tuple[str, str], ...] = (
    ("easydict", "easydict"),
    ("filelock", "filelock"),
    ("numpy", "numpy"),
    ("pillow", "PIL"),
    ("plyfile", "plyfile"),
    ("tqdm", "tqdm"),
    ("trimesh", "trimesh"),
    ("zstandard", "zstandard"),
)
# rembg is in ComfyUI-Trellis2/requirements.txt but the extra does not pull
# onnxruntime on Ashley; without it Trellis2PreProcessImage hangs.
TRELLIS2_PY_DEPS: tuple[tuple[str, str], ...] = (
    ("onnxruntime", "onnxruntime"),
)

def _lock_has_pixal3d(nodes: Iterable[Mapping[str, Any]]) -> bool:
    return any("pixal3d" in str(node.get("id") or "").lower() for node in nodes)


def _lock_has_trellis2(nodes: Iterable[Mapping[str, Any]]) -> bool:
    return any("trellis2" in str(node.get("id") or "").lower() for node in nodes)


def _lock_needs_sparse_3d_runtime(nodes: Iterable[Mapping[str, Any]]) -> bool:
    return _lock_has_pixal3d(nodes) or _lock_has_trellis2(nodes)


def _find_pixal3d_node_dir(custom_nodes_dir: Path) -> Path | None:
    if not custom_nodes_dir.is_dir():
        return None
    for item in sorted(custom_nodes_dir.iterdir()):
        if item.is_dir() and "pixal3d" in item.name.lower():
            return item
    return None


def natten_wheel_spec(
    torch_version: str, natten_version: str = NATTEN_DEFAULT_VERSION
) -> str:
    """Map ``2.11.0+cu128`` to ``0.21.6+torch2110cu128`` for whl.natten.org."""
    public = torch_version.split()[0]
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\+cu(\d+))?", public)
    if match is None:
        raise ValueError(f"unrecognized torch version: {torch_version}")
    major, minor, patch, cuda = match.groups()
    local = f"torch{major}{minor}{patch}"
    if cuda:
        local += f"cu{cuda}"
    return f"{natten_version}+{local}"


def flash_attn_wheel_url(python_version: str, torch_version: str) -> str | None:
    """Prebuilt flash-attn 2.8.3 for Ashley's torch 2.11 + CUDA 12.8 stack."""
    python_mm = ".".join(python_version.split(".")[:2])
    torch_mm = ".".join(torch_version.split("+")[0].split(".")[:2])
    if torch_mm != "2.11" or python_mm not in {"3.10", "3.11", "3.12", "3.13"}:
        return None
    return FLASH_ATTN_TORCH211_WHEEL.format(py=python_mm.replace(".", ""))


def sparse_3d_wheel_urls(
    python_version: str,
    torch_version: str,
    *,
    include_drtk: bool = False,
    include_nvdiffrast: bool = False,
) -> tuple[tuple[str, tuple[str, ...], str], ...]:
    """PozzettiAndrea CUDA wheels for Ashley's cp312 + torch 2.11 + cu128."""
    python_mm = ".".join(python_version.split(".")[:2])
    public = torch_version.split()[0]
    if python_mm != "3.12" or not public.startswith("2.11.0") or "+cu128" not in public:
        return ()
    rows = list(SPARSE_3D_WHEEL_FILES)
    if include_drtk:
        rows.append(DRTK_WHEEL_FILE)
    if include_nvdiffrast:
        rows.extend(TRELLIS2_WHEEL_FILES)
    return tuple(
        (
            label,
            imports,
            f"{CUDA_WHEEL_RELEASE}/{tag}/{quote(filename, safe='.-_')}",
        )
        for label, imports, tag, filename in rows
    )


def requirements_without_packages(text: str, skip: frozenset[str]) -> str:
    kept: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            kept.append(line)
            continue
        package = re.split(r"[<>=!~\[\s]", stripped, maxsplit=1)[0].strip().lower()
        if package in skip:
            continue
        kept.append(line)
    return "".join(kept)


def natten_requirement_version(
    text: str, default: str = NATTEN_DEFAULT_VERSION
) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("natten"):
            match = re.search(r"==\s*([0-9][0-9.]*)", stripped)
            if match:
                return match.group(1)
    return default

def _ensure_cuda_build_tools() -> None:
    cuda_bin = Path("/usr/local/cuda/bin")
    if cuda_bin.is_dir():
        os.environ["PATH"] = f"{cuda_bin}:{os.environ.get('PATH', '')}"
    if shutil.which("cmake") and shutil.which("nvcc"):
        return
    if not shutil.which("apt-get"):
        print("[PIXAL3D] cmake/nvcc missing and apt-get is unavailable", flush=True)
        return
    _run(["apt-get", "update"])
    _run(
        [
            "apt-get",
            "install",
            "-y",
            "cmake",
            "ninja-build",
            "build-essential",
            "python3-dev",
        ]
    )


def _install_natten_wheel(
    python: str, natten_version: str = NATTEN_DEFAULT_VERSION
) -> bool:
    try:
        spec = _ce().natten_wheel_spec(
            _python_text(python, "import torch; print(torch.__version__)"),
            natten_version,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
        ValueError,
    ) as exc:
        print(f"[PIXAL3D] cannot map torch to a natten wheel ({exc})", flush=True)
        return False
    print(
        f"[PIXAL3D] pip install natten=={spec} from {NATTEN_WHEEL_INDEX}",
        flush=True,
    )
    try:
        _run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--no-cache-dir",
                "--only-binary=:all:",
                f"natten=={spec}",
                "-f",
                NATTEN_WHEEL_INDEX,
            ]
        )
    except subprocess.CalledProcessError:
        print("[PIXAL3D] natten wheel missing; will fall back to sdist", flush=True)
        return False
    return _module_available("natten", python)


def _install_flash_attn_wheel(python: str) -> bool:
    try:
        python_version = _python_text(
            python,
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        )
        torch_version = _python_text(python, "import torch; print(torch.__version__)")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"[PIXAL3D] cannot map torch to a flash-attn wheel ({exc})", flush=True)
        return False
    url = _ce().flash_attn_wheel_url(python_version, torch_version)
    if url is None:
        print(
            f"[PIXAL3D] no flash-attn wheel for python {python_version} torch {torch_version}",
            flush=True,
        )
        return False
    print(f"[PIXAL3D] pip install flash-attn wheel {url}", flush=True)
    try:
        _run([python, "-m", "pip", "install", "--no-cache-dir", url])
    except subprocess.CalledProcessError:
        print(
            "[PIXAL3D] flash-attn wheel install failed; will fall back to source",
            flush=True,
        )
        return False
    return _module_available("flash_attn", python) or _module_available(
        "flash_attn_interface", python
    )


def _install_sparse_3d_python_deps(python: str) -> bool:
    missing = [
        pip_name
        for pip_name, import_name in SPARSE_3D_WHEEL_PY_DEPS
        if not _module_available(import_name, python)
    ]
    if not missing:
        return False
    print(f"[PIXAL3D] pip install sparse-3d python deps {missing}", flush=True)
    _run([python, "-m", "pip", "install", "--no-cache-dir", *missing])
    return True


def _install_trellis2_python_deps(python: str) -> bool:
    missing = [
        pip_name
        for pip_name, import_name in TRELLIS2_PY_DEPS
        if not _module_available(import_name, python)
    ]
    if not missing:
        return False
    print(f"[TRELLIS2] pip install python deps {missing}", flush=True)
    _run([python, "-m", "pip", "install", "--no-cache-dir", *missing])
    return True


def _ensure_opengl_libs() -> None:
    """pymeshlab plugins need libOpenGL.so.0; Ashley image does not ship it."""
    candidates = (
        Path("/usr/lib/x86_64-linux-gnu/libOpenGL.so.0"),
        Path("/usr/lib/libOpenGL.so.0"),
    )
    if any(path.exists() for path in candidates):
        return
    if not shutil.which("apt-get"):
        print("[TRELLIS2] libOpenGL.so.0 missing and apt-get is unavailable", flush=True)
        return
    print("[TRELLIS2] apt-get install libopengl0 libgl1", flush=True)
    _run(["apt-get", "update"])
    _run(["apt-get", "install", "-y", "libopengl0", "libgl1"])


def _alias_sparse_3d_packages(python: str) -> bool:
    """PozzettiAndrea wheels import as *_vb / *_ap; Trellis2 imports o_voxel / cumesh / flex_gemm."""
    purelib = _site_packages(python)
    if purelib is None:
        print("[PIXAL3D] cannot locate site-packages for CUDA aliases", flush=True)
        return False
    aliases = (
        ("o_voxel_vb_ap", "o_voxel"),
        ("flex_gemm_ap", "flex_gemm"),
        ("cumesh_vb", "cumesh"),
    )
    changed = False
    for source, alias in aliases:
        src = purelib / source
        dest = purelib / alias
        if not src.is_dir():
            continue
        if dest.is_symlink() and dest.resolve() == src.resolve():
            continue
        if dest.exists() or dest.is_symlink():
            if dest.is_dir() and not dest.is_symlink():
                print(f"[PIXAL3D] skip alias {alias}: {dest} already exists", flush=True)
                continue
            dest.unlink()
        dest.symlink_to(src, target_is_directory=True)
        print(f"[PIXAL3D] alias {alias} -> {source}", flush=True)
        changed = True
    return changed


BLACKWELL_BOOT_PY = '''\
"""Load before ComfyUI-Trellis2. RTX PRO 6000 is Blackwell sm_120.

Do not import torch here. A venv .pth runs before --system-site-packages is
on sys.path (Ashley keeps torch in dist-packages), so `import torch` would
fail and also print onto stdout that `_python_text` captures as a path.
"""
from __future__ import annotations

import builtins
import os
import sys

os.environ.setdefault("ATTN_BACKEND", "sdpa")
os.environ.setdefault("SPARSE_CONV_BACKEND", "spconv")

_applied = False
_orig_import = builtins.__import__


def _apply_patch() -> None:
    global _applied
    if _applied:
        return
    try:
        torch = _orig_import("torch")
    except Exception:
        return
    if not getattr(torch, "cuda", None) or not torch.cuda.is_available():
        _applied = True
        return
    try:
        major, _minor = torch.cuda.get_device_capability(0)
    except Exception:
        return
    if major < 10:
        _applied = True
        return
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    orig = torch.cuda.get_device_capability

    def _cap(device=None):
        m, n = orig(device)
        return (9, 0) if m >= 10 else (m, n)

    torch.cuda.get_device_capability = _cap
    _applied = True
    print("[TRELLIS2] Blackwell CC patch -> (9, 0)", file=sys.stderr, flush=True)


def _import(name, globals=None, locals=None, fromlist=(), level=0):
    module = _orig_import(name, globals, locals, fromlist, level)
    root = name.split(".", 1)[0]
    if level == 0 and root == "torch":
        try:
            _apply_patch()
        except Exception:
            pass
    return module


builtins.__import__ = _import
'''


def _install_blackwell_boot(python: str) -> bool:
    """sitecustomize-style .pth so the ComfyUI subprocess gets the CC patch."""
    purelib = _site_packages(python)
    if purelib is None:
        print("[TRELLIS2] cannot write Blackwell boot", flush=True)
        return False
    boot = purelib / "trellis2_blackwell_boot.py"
    pth = purelib / "trellis2_blackwell.pth"
    changed = False
    if not boot.is_file() or boot.read_text(encoding="utf-8") != BLACKWELL_BOOT_PY:
        boot.write_text(BLACKWELL_BOOT_PY, encoding="utf-8")
        changed = True
    marker = "import trellis2_blackwell_boot\n"
    if not pth.is_file() or pth.read_text(encoding="utf-8") != marker:
        pth.write_text(marker, encoding="utf-8")
        changed = True
    if changed:
        print("[TRELLIS2] installed Blackwell boot for ComfyUI subprocess", flush=True)
    return changed


def _install_sparse_3d_prebuilt_wheels(
    python: str, *, include_drtk: bool, include_nvdiffrast: bool = False
) -> bool:
    """Install flex_gemm / cumesh / o-voxel (and optional DRTK) from CUDA wheels."""
    try:
        python_version = _python_text(python, "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        torch_version = _python_text(python, "import torch; print(torch.__version__)")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"[PIXAL3D] cannot map python/torch to sparse-3d wheels ({exc})", flush=True)
        return False
    specs = _ce().sparse_3d_wheel_urls(
        python_version,
        torch_version,
        include_drtk=include_drtk,
        include_nvdiffrast=include_nvdiffrast,
    )
    if not specs:
        print(
            f"[PIXAL3D] no sparse-3d wheels for python {python_version} torch {torch_version}",
            flush=True,
        )
        return False
    changed = _ce()._install_sparse_3d_python_deps(python)
    changed = _ce()._alias_sparse_3d_packages(python) or changed
    for label, imports, url in specs:
        if any(_module_available(name, python) for name in imports):
            print(f"[PIXAL3D] {label} already importable", flush=True)
            continue
        print(f"[PIXAL3D] pip install {label} wheel {url}", flush=True)
        try:
            _run([python, "-m", "pip", "install", "--no-cache-dir", "--no-deps", url])
        except subprocess.CalledProcessError:
            print(f"[PIXAL3D] {label} wheel install failed", flush=True)
            continue
        if any(_module_available(name, python) for name in imports):
            changed = True
            continue
        errors = [
            f"{name}: {_module_import_error(name, python)}"
            for name in imports
            if _module_import_error(name, python)
        ]
        print(
            f"[PIXAL3D] {label} wheel installed but still not importable ({'; '.join(errors)})",
            flush=True,
        )
    return changed


def ensure_pixal3d_prebuilt_wheels(
    comfy_root: str | Path,
    *,
    include_attention: bool = True,
    include_sparse: bool = True,
    include_drtk: bool = False,
    include_nvdiffrast: bool = False,
) -> bool:
    """Install official/community CUDA wheels before CNR can compile sdists."""
    python = _comfy_python(Path(comfy_root))
    changed = False
    if include_attention:
        if not _module_available("natten", python):
            changed = _ce()._install_natten_wheel(python) or changed
        attention_ok = _module_available("flash_attn", python) or _module_available(
            "flash_attn_interface", python
        )
        if not attention_ok:
            changed = _ce()._install_flash_attn_wheel(python) or changed
    if include_sparse:
        changed = (
            _ce()._install_sparse_3d_prebuilt_wheels(
                python,
                include_drtk=include_drtk,
                include_nvdiffrast=include_nvdiffrast,
            )
            or changed
        )
    return changed


def ensure_pixal3d_runtime(
    comfy_root: str | Path,
    custom_nodes_dir: str | Path,
    *,
    include_pixal3d: bool = False,
    include_trellis2: bool = False,
    allow_source_compile: bool = False,
) -> bool:
    """Install sparse-3D Python deps and CUDA kernels (Pixal3D / TRELLIS.2).

    natten / flash-attn / flex_gemm / cumesh / o-voxel (and Pixal3D DRTK)
    use prebuilt wheels on Ashley's cp312 + torch 2.11 + cu128 stack.
    Pixal3D ``requirements.txt`` / DRTK only run when the *current lock*
    asks for Pixal3D — leftover node dirs on the Volume are ignored.
    Source compile is opt-in; default is wheel-only so GPU start does not
    compile CUDA.
    Returns True if anything was installed (ComfyUI should restart).
    """
    comfy_root = Path(comfy_root)
    python = _comfy_python(comfy_root)
    changed = _ce().ensure_pixal3d_prebuilt_wheels(
        comfy_root,
        include_attention=include_pixal3d,
        include_sparse=True,
        include_drtk=include_pixal3d,
        include_nvdiffrast=include_trellis2,
    )
    node_dir = (
        _ce()._find_pixal3d_node_dir(Path(custom_nodes_dir)) if include_pixal3d else None
    )

    requirements = node_dir / "requirements.txt" if node_dir is not None else None
    if requirements is not None and requirements.is_file() and (
        not _module_available("moge", python) or not _module_available("natten", python)
    ):
        filtered = Path("/tmp/pixal3d-requirements-no-natten.txt")
        source = requirements.read_text(encoding="utf-8")
        filtered.write_text(
            _ce().requirements_without_packages(source, frozenset({"natten"})),
            encoding="utf-8",
        )
        print("[PIXAL3D] pip install requirements.txt (natten uses a prebuilt wheel)", flush=True)
        _run([python, "-m", "pip", "install", "--no-cache-dir", "-r", str(filtered)])
        changed = True
        if not _module_available("natten", python):
            if not allow_source_compile:
                raise RuntimeError(
                    "natten wheel missing or not importable; GPU source compile is disabled"
                )
            pin = _ce().natten_requirement_version(source)
            print(f"[PIXAL3D] compiling natten=={pin} from source", flush=True)
            _ce()._ensure_cuda_build_tools()
            _run([python, "-m", "pip", "install", "--no-cache-dir", f"natten=={pin}"])

    if include_pixal3d:
        attention_ok = _module_available("flash_attn", python) or _module_available(
            "flash_attn_interface", python
        )
        if not attention_ok:
            if not _ce()._install_flash_attn_wheel(python):
                if not allow_source_compile:
                    raise RuntimeError(
                        "flash-attn wheel missing or not importable; "
                        "GPU source compile is disabled"
                    )
                print("[PIXAL3D] pip install flash-attn from source", flush=True)
                _ce()._ensure_cuda_build_tools()
                _run(
                    [
                        python,
                        "-m",
                        "pip",
                        "install",
                        "--no-cache-dir",
                        "--no-build-isolation",
                        "flash-attn",
                    ]
                )
            changed = True

    changed = (
        _ce()._install_sparse_3d_prebuilt_wheels(
            python,
            include_drtk=include_pixal3d,
            include_nvdiffrast=include_trellis2,
        )
        or changed
    )
    if include_trellis2:
        changed = _ce()._install_trellis2_python_deps(python) or changed
        _ce()._ensure_opengl_libs()
        changed = _ce()._install_blackwell_boot(python) or changed

    tmp = Path("/tmp/pixal3d_extensions")
    tmp.mkdir(parents=True, exist_ok=True)
    sources: list[tuple[str, tuple[str, ...], list[str], str | None]] = [
        (
            "flex_gemm",
            ("flex_gemm_ap", "flex_gemm"),
            [
                "git",
                "clone",
                "--depth=1",
                "--recursive",
                "--shallow-submodules",
                "https://github.com/JeffreyXiang/FlexGEMM.git",
            ],
            None,
        ),
        (
            "cumesh",
            ("cumesh_vb", "cumesh"),
            [
                "git",
                "clone",
                "--depth=1",
                "--recursive",
                "--shallow-submodules",
                "https://github.com/JeffreyXiang/CuMesh.git",
            ],
            None,
        ),
        (
            "o_voxel",
            ("o_voxel_vb_ap", "o_voxel"),
            ["git", "clone", "--depth=1", "https://github.com/microsoft/TRELLIS.2.git"],
            "o-voxel",
        ),
    ]
    if include_pixal3d:
        sources.append(
            (
                "drtk",
                ("drtk",),
                [
                    "git",
                    "clone",
                    "--depth=1",
                    "--branch",
                    "stable",
                    "https://github.com/facebookresearch/DRTK.git",
                ],
                None,
            )
        )
    missing = [
        item
        for item in sources
        if not any(_module_available(name, python) for name in item[1])
    ]
    if not missing:
        return changed

    if not allow_source_compile:
        details: list[str] = []
        for label, imports, _clone, _subdir in missing:
            for name in imports:
                error = _module_import_error(name, python)
                if error:
                    details.append(f"{label}/{name}: {error}")
                    break
        raise RuntimeError(
            "sparse-3D CUDA wheels missing or not importable: "
            + ", ".join(item[0] for item in missing)
            + ". GPU source compile is disabled. "
            + " ".join(details)
        )

    _ce()._ensure_cuda_build_tools()
    for label, imports, clone, subdir in missing:
        dest = tmp / label
        if dest.exists():
            shutil.rmtree(dest)
        print(f"[PIXAL3D] build {label} from source (no matching wheel)", flush=True)
        _run([*clone, str(dest)])
        install_path = str(dest / subdir) if subdir else str(dest)
        _run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--no-cache-dir",
                "--no-deps",
                "--no-build-isolation",
                install_path,
            ]
        )
        changed = True
        if not any(_module_available(name, python) for name in imports):
            raise RuntimeError(
                f"Pixal3D CUDA extension {label} installed but still not importable"
            )
    return changed


ensure_sparse_3d_prebuilt_wheels = ensure_pixal3d_prebuilt_wheels
ensure_sparse_3d_runtime = ensure_pixal3d_runtime
