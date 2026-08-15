"""GitHub base custom-node distribution for the Modal ComfyUI image.

``nodes.md`` from ComfyUI-yi_dian_tong is only a directory-name list. The CNB
git repo does **not** contain ``ComfyUI/custom_nodes`` (sparse checkout yields
empty trees). The real plugins live in the CNB Docker images, which were
themselves built with ``cm-cli.sh install`` / ``git clone`` of GitHub URLs.

This installer shallow-clones those upstream GitHub repositories into the
Ashley image using the exact ``nodes.md`` directory names, without a branch
or SHA pin, so ``modal serve`` (``force_build``) always gets default-branch
HEAD. It does **not** ``COPY --from`` the 23GiB+ CNB runtime image.

``comfyui_modal.py`` copies this file into the image via
``Image.add_local_file(..., copy=True)`` and runs it with the Ashley venv
Python. Modal wraps ``run_commands`` into Dockerfile ``RUN`` layers and does
not support shell heredocs or giant nested ``python -c`` payloads.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE_NODES_SOURCE = "https://cnb.cool/SKDZSS90/ComfyUI-yi_dian_tong/-/blob/main/nodes.md"
BASE_NODES_REPOSITORY = "https://cnb.cool/SKDZSS90/ComfyUI-yi_dian_tong.git"
BASE_NODES_IMAGE = "docker.cnb.cool/skdzss90/fenxiang/py312_t291_c130:xin-L40g-0811"
BASE_NODES_IMAGE_FALLBACK = "docker.cnb.cool/skdzss90/fenxiang/3lian_guan_zhu:0531-v.0.3.39-n120"
BASE_NODES_SNAPSHOT = "2026-08-12"

# Path where comfyui_modal.py places this file inside the build image.
INSTALLER_REMOTE_PATH = "/opt/comfy-base-nodes/base_nodes.py"

# Directory name from nodes.md → upstream git URL recovered from CNB image
# history (plus GitHub lookups for nodes added after those Dockerfiles).
# ``None`` means skip clone (Manager is installed with uv pip).
BASE_NODE_SOURCES: tuple[tuple[str, str | None], ...] = (
    ("a-person-mask-generator", "https://github.com/djbielejeski/a-person-mask-generator.git"),
    ("audio-separation-nodes-comfyui", "https://github.com/christian-byrne/audio-separation-nodes-comfyui.git"),
    ("cg-image-filter", "https://github.com/chrisgoringe/cg-image-filter.git"),
    ("comfy-mtb", "https://github.com/melMass/comfy_mtb.git"),
    ("ComfyLiterals", "https://github.com/M1kep/ComfyLiterals.git"),
    ("ComfyMath", "https://github.com/evanspearman/ComfyMath.git"),
    ("ComfyQR", "https://github.com/coreyryanhanson/ComfyQR.git"),
    ("ComfyUI_ADV_CLIP_emb", "https://github.com/BlenderNeko/ComfyUI_ADV_CLIP_emb.git"),
    ("ComfyUI_AdvancedRefluxControl", "https://github.com/kaibioinfo/ComfyUI_AdvancedRefluxControl.git"),
    ("Comfyui_Comfly", "https://github.com/ainewsto/Comfyui_Comfly.git"),
    ("ComfyUI_Comfyroll_CustomNodes", "https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes.git"),
    ("comfyui_controlnet_aux", "https://github.com/Fannovel16/comfyui_controlnet_aux.git"),
    ("comfyui_custom_nodes_alekpet", "https://github.com/AlekPet/ComfyUI_Custom_Nodes_AlekPet.git"),
    ("comfyui_essentials", "https://github.com/cubiq/ComfyUI_essentials.git"),
    ("comfyui_facesimilarity", "https://github.com/chflame163/ComfyUI_FaceSimilarity.git"),
    ("ComfyUI_Fill-Nodes", "https://github.com/filliptm/ComfyUI_Fill-Nodes.git"),
    ("ComfyUI_FizzNodes", "https://github.com/FizzleDorf/ComfyUI_FizzNodes.git"),
    ("comfyui_instantid", "https://github.com/cubiq/ComfyUI_InstantID.git"),
    ("comfyui_ipadapter_plus", "https://github.com/cubiq/ComfyUI_IPAdapter_plus.git"),
    ("ComfyUI_LayerStyle_Advance", "https://github.com/chflame163/ComfyUI_LayerStyle_Advance.git"),
    ("ComfyUI_LayerStyle", "https://github.com/chflame163/ComfyUI_LayerStyle.git"),
    ("Comfyui_LG_Tools", "https://github.com/LAOGOU-666/Comfyui_LG_Tools.git"),
    ("ComfyUi_NNLatentUpscale", "https://github.com/Ttl/ComfyUi_NNLatentUpscale.git"),
    ("comfyui_patches_ll", "https://github.com/lldacing/ComfyUI_Patches_ll.git"),
    ("Comfyui_PDuse", "https://github.com/7BEII/Comfyui_PDuse.git"),
    ("comfyui_pops", "https://github.com/smthemex/ComfyUI_Pops.git"),
    ("comfyui_prompt_assistant", "https://github.com/yawiii/ComfyUI-Prompt-Assistant.git"),
    ("comfyui_pulid_flux_ll", "https://github.com/lldacing/ComfyUI_PuLID_Flux_ll.git"),
    ("comfyui_segment_anything", "https://github.com/storyicon/comfyui_segment_anything.git"),
    ("comfyui_slk_joy_caption_two", "https://github.com/EvilBT/ComfyUI_SLK_joy_caption_two.git"),
    ("ComfyUI_Sonic", "https://github.com/smthemex/ComfyUI_Sonic.git"),
    ("ComfyUI_Text_Translation", "https://github.com/TFL-TFL/ComfyUI_Text_Translation.git"),
    ("comfyui_ttp_toolset", "https://github.com/TTPlanetPig/Comfyui_TTP_Toolset.git"),
    ("comfyui_ultimatesdupscale", "https://github.com/ssitu/ComfyUI_UltimateSDUpscale.git"),
    ("ComfyUI_YuE", "https://github.com/smthemex/ComfyUI_YuE.git"),
    ("ComfyUI-AnimateDiff-Evolved", "https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git"),
    ("ComfyUI-Anyline", "https://github.com/TheMistoAI/ComfyUI-Anyline.git"),
    ("comfyui-art-venture", "https://github.com/sipherxyz/comfyui-art-venture.git"),
    ("ComfyUI-AutoCropFaces", "https://github.com/liusida/ComfyUI-AutoCropFaces.git"),
    ("ComfyUI-Basic-Math", "https://github.com/akatz-ai/ComfyUI-Basic-Math.git"),
    ("comfyui-browser", "https://github.com/talesofai/comfyui-browser.git"),
    ("comfyui-brushnet", "https://github.com/nullquant/ComfyUI-BrushNet.git"),
    ("ComfyUI-Crystools", "https://github.com/crystian/ComfyUI-Crystools.git"),
    ("comfyui-custom-scripts", "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git"),
    ("ComfyUI-DD-Translation", "https://github.com/1761696257/ComfyUI-DD-Translation.git"),
    ("comfyui-depthanythingv2", "https://github.com/kijai/ComfyUI-DepthAnythingV2.git"),
    ("comfyui-detail-daemon", "https://github.com/Jonseed/ComfyUI-Detail-Daemon.git"),
    ("ComfyUI-Easy-Use", "https://github.com/yolain/ComfyUI-Easy-Use.git"),
    ("ComfyUI-Embedding_Picker", "https://github.com/Tropfchen/ComfyUI-Embedding_Picker.git"),
    ("ComfyUI-fastblend", "https://github.com/AInseven/ComfyUI-fastblend.git"),
    ("comfyui-fitsize", "https://github.com/bronkula/comfyui-fitsize.git"),
    ("ComfyUI-FlashVSR_Ultra_Fast", "https://github.com/lihaoyun6/ComfyUI-FlashVSR_Ultra_Fast.git"),
    ("comfyui-florence2", "https://github.com/kijai/ComfyUI-Florence2.git"),
    ("comfyui-frame-interpolation", "https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git"),
    ("ComfyUI-FramePackWrapper", "https://github.com/kijai/ComfyUI-FramePackWrapper.git"),
    ("ComfyUI-GGUF", "https://github.com/city96/ComfyUI-GGUF.git"),
    ("ComfyUI-GIMM-VFI", "https://github.com/kijai/ComfyUI-GIMM-VFI.git"),
    ("ComfyUI-GlifNodes", "https://github.com/glifxyz/ComfyUI-GlifNodes.git"),
    ("ComfyUI-GLM4", "https://github.com/msola-ht/ComfyUI-GLM4.git"),
    ("ComfyUI-GradientBlur", "https://github.com/badxprogramm/ComfyUI-GradientBlur.git"),
    ("ComfyUI-HunyuanVideoWrapper", "https://github.com/kijai/ComfyUI-HunyuanVideoWrapper.git"),
    ("comfyui-ic-light-native", "https://github.com/huchenlei/ComfyUI-IC-Light-Native.git"),
    ("ComfyUI-IC-Light", "https://github.com/kijai/ComfyUI-IC-Light.git"),
    ("comfyui-imagesubfolders", "https://github.com/catscandrive/comfyui-imagesubfolders.git"),
    ("ComfyUI-Impact-Pack", "https://github.com/ltdrdata/ComfyUI-Impact-Pack.git"),
    ("comfyui-impact-subpack", "https://github.com/ltdrdata/ComfyUI-Impact-Subpack.git"),
    ("comfyui-in-context-lora-utils", "https://github.com/lrzjason/Comfyui-In-Context-Lora-Utils.git"),
    ("comfyui-inpaint-cropandstitch", "https://github.com/lquesada/ComfyUI-Inpaint-CropAndStitch.git"),
    ("comfyui-inpaint-nodes", "https://github.com/Acly/comfyui-inpaint-nodes.git"),
    ("comfyui-inspire-pack", "https://github.com/ltdrdata/ComfyUI-Inspire-Pack.git"),
    ("comfyui-inspyrenet-rembg", "https://github.com/john-mnz/ComfyUI-Inspyrenet-Rembg.git"),
    ("ComfyUI-IPAdapter-Flux", "https://github.com/Shakker-Labs/ComfyUI-IPAdapter-Flux.git"),
    ("ComfyUI-KJNodes", "https://github.com/kijai/ComfyUI-KJNodes.git"),
    ("comfyui-lama-remover", "https://github.com/Layer-norm/comfyui-lama-remover.git"),
    ("comfyui-layerdiffuse", "https://github.com/huchenlei/ComfyUI-layerdiffuse.git"),
    # Original dorpxam/ComfyUI-LTXVideoLoRA was deleted; this is the archived copy.
    ("comfyui-ltxvideolora", "https://github.com/ComfyNodePRs/PR-ComfyUI-LTXVideoLoRA-f5876a9a.git"),
    ("comfyui-lumi-batcher", "https://github.com/bytedance/comfyui-lumi-batcher.git"),
    ("comfyui-manager", None),
    ("ComfyUI-Marigold", "https://github.com/kijai/ComfyUI-Marigold.git"),
    ("ComfyUI-MelBandRoFormer", "https://github.com/kijai/ComfyUI-MelBandRoFormer.git"),
    ("ComfyUI-MingNodes", "https://github.com/mingsky-ai/ComfyUI-MingNodes.git"),
    ("comfyui-mixlab-nodes", "https://github.com/jtydhr88/comfyui-mixlab-nodes.git"),
    ("comfyui-openai-fm", "https://github.com/fairy-root/ComfyUI-OpenAI-FM.git"),
    ("comfyui-openpose-editor", "https://github.com/huchenlei/ComfyUI-openpose-editor.git"),
    ("ComfyUI-Ovi", "https://github.com/snicolast/ComfyUI-Ovi.git"),
    ("comfyui-post-processing-nodes", "https://github.com/EllangoK/ComfyUI-post-processing-nodes.git"),
    ("ComfyUi-RadarWeightNode", "https://github.com/FunnyFinger/ComfyUi-RadarWeightNode.git"),
    ("ComfyUI-ReActor", "https://github.com/Gourieff/ComfyUI-ReActor.git"),
    ("comfyui-redux-prompt", "https://github.com/CY-CHENYUE/ComfyUI-Redux-Prompt.git"),
    ("ComfyUI-RMBG", "https://github.com/1038lab/ComfyUI-RMBG.git"),
    ("comfyui-saveimage-plus", "https://github.com/Goktug/comfyui-saveimage-plus.git"),
    ("Comfyui-SecNodes", "https://github.com/9nate-drake/Comfyui-SecNodes.git"),
    ("ComfyUI-SeedVR2_VideoUpscaler", "https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler.git"),
    ("ComfyUI-segment-anything-2", "https://github.com/kijai/ComfyUI-segment-anything-2.git"),
    ("ComfyUI-SoundFlow", "https://github.com/huixingyun/ComfyUI-SoundFlow.git"),
    ("comfyui-stringsandthings", "https://github.com/PressWagon/ComfyUI-StringsAndThings.git"),
    ("comfyui-supir", "https://github.com/kijai/ComfyUI-SUPIR.git"),
    ("comfyui-tensorops", "https://github.com/un-seen/comfyui-tensorops.git"),
    ("ComfyUI-Tripo", "https://github.com/VAST-AI-Research/ComfyUI-Tripo.git"),
    ("ComfyUI-UVR5", "https://github.com/AIFSH/ComfyUI-UVR5.git"),
    ("comfyui-various", "https://github.com/jamesWalker55/comfyui-various.git"),
    ("comfyui-video-matting", "https://github.com/Fannovel16/ComfyUI-Video-Matting.git"),
    ("ComfyUI-VideoBasic", "https://github.com/jax-explorer/ComfyUI-VideoBasic.git"),
    ("ComfyUI-VideoHelperSuite", "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git"),
    ("ComfyUI-WanAnimatePreprocess", "https://github.com/kijai/ComfyUI-WanAnimatePreprocess.git"),
    ("ComfyUI-WanStartEndFramesNative", "https://github.com/Flow-two/ComfyUI-WanStartEndFramesNative.git"),
    ("ComfyUI-WanVideoStartEndFrames", "https://github.com/raindrop313/ComfyUI-WanVideoStartEndFrames.git"),
    ("ComfyUI-WanVideoWrapper", "https://github.com/kijai/ComfyUI-WanVideoWrapper.git"),
    ("comfyui-wd14-tagger", "https://github.com/pythongosssss/ComfyUI-WD14-Tagger.git"),
    ("ComfyUI-YCNodes", "https://github.com/yichengup/ComfyUI-YCNodes.git"),
    ("D2-SavePSD-ComfyUI", "https://github.com/da2el-ai/D2-SavePSD-ComfyUI.git"),
    ("efficiency-nodes-comfyui", "https://github.com/jags111/efficiency-nodes-comfyui.git"),
    ("flux-prompt-generator", "https://github.com/fairy-root/Flux-Prompt-Generator.git"),
    ("images_base64", "https://github.com/GrailGreg/images_base64.git"),
    ("janus-pro", "https://github.com/CY-CHENYUE/ComfyUI-Janus-Pro.git"),
    ("joycaption_comfyui", "https://github.com/fpgaminer/joycaption_comfyui.git"),
    ("komojini-comfyui-nodes", "https://github.com/komojini/komojini-comfyui-nodes.git"),
    ("mikey_nodes", "https://github.com/bash-j/mikey_nodes.git"),
    ("OneButtonPrompt", "https://github.com/AIrjen/OneButtonPrompt.git"),
    ("portraittools-mw", "https://github.com/billwuhao/ComfyUI_PortraitTools.git"),
    ("pulid_comfyui", "https://github.com/cubiq/PuLID_ComfyUI.git"),
    ("rembg-comfyui-node-better", "https://github.com/Loewen-Hob/rembg-comfyui-node-better.git"),
    ("rgthree-comfy", "https://github.com/rgthree/rgthree-comfy.git"),
    ("skimmed_cfg", "https://github.com/Extraltodeus/Skimmed_CFG.git"),
    ("stability-ComfyUI-nodes", "https://github.com/Stability-AI/stability-ComfyUI-nodes.git"),
    ("teacache", "https://github.com/welltop-cn/ComfyUI-TeaCache.git"),
    ("wanblockswap", "https://github.com/orssorbit/ComfyUI-wanBlockswap.git"),
    ("was-node-suite-comfyui", "https://github.com/WASasquatch/was-node-suite-comfyui.git"),
    ("wavespeed", "https://github.com/chengzeyi/Comfy-WaveSpeed.git"),
    ("x-flux-comfyui", "https://github.com/XLabs-AI/x-flux-comfyui.git"),
)

BASE_NODE_NAMES: tuple[str, ...] = tuple(name for name, _url in BASE_NODE_SOURCES)
BASE_NODE_REPOS: dict[str, str] = {name: url for name, url in BASE_NODE_SOURCES if url}
BASE_NODE_COUNT = len(BASE_NODE_NAMES)
assert BASE_NODE_COUNT == 130
assert len(set(BASE_NODE_NAMES)) == BASE_NODE_COUNT
assert len(BASE_NODE_REPOS) == BASE_NODE_COUNT - 1
assert "comfyui-manager" in BASE_NODE_NAMES
assert "comfyui-manager" not in BASE_NODE_REPOS

_CLONE_WORKERS = 8
_ASKPASS_PATH = Path("/tmp/comfy-git-askpass")


def _git_env() -> dict[str, str]:
    """Inherit the image-build env and enable GitHub token auth when present."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    token = env.get("GITHUB_TOKEN", "").strip()
    if token and not env.get("GIT_ASKPASS"):
        _ASKPASS_PATH.write_text(
            "#!/bin/sh\n"
            'case "$1" in *Username*) echo x-access-token ;; *) echo "$GITHUB_TOKEN" ;; esac\n',
            encoding="utf-8",
        )
        _ASKPASS_PATH.chmod(_ASKPASS_PATH.stat().st_mode | stat.S_IXUSR)
        env["GIT_ASKPASS"] = str(_ASKPASS_PATH)
    return env


def _clone_repo(url: str, dest: Path) -> None:
    """Shallow-clone ``url`` into ``dest`` (the nodes.md directory name)."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth=1", url, str(dest)],
        check=True,
        env=_git_env(),
    )
    contents = [path for path in dest.iterdir() if path.name != ".git"]
    if not contents:
        raise RuntimeError(f"cloned {url} into {dest} but the working tree is empty")


def _clone_base_nodes(dst_root: Path) -> None:
    dst_root.mkdir(parents=True, exist_ok=True)
    items = list(BASE_NODE_REPOS.items())
    errors: list[str] = []

    def work(name: str, url: str) -> None:
        print(f"clone {name} <- {url}", flush=True)
        _clone_repo(url, dst_root / name)

    with ThreadPoolExecutor(max_workers=_CLONE_WORKERS) as pool:
        futures = {pool.submit(work, name, url): name for name, url in items}
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as exc:  # noqa: BLE001 — surface every clone failure
                errors.append(f"{name}: {exc}")

    if errors:
        raise SystemExit(
            "Failed to clone pinned base custom nodes:\n" + "\n".join(errors)
        )


def _copy_base_nodes(src_root: Path, dst_root: Path, wanted: list[str]) -> None:
    missing = [name for name in wanted if not (src_root / name).is_dir()]
    if missing:
        raise SystemExit(
            "Pinned snapshot is missing expected custom nodes: " + ", ".join(missing)
        )

    dst_root.mkdir(parents=True, exist_ok=True)
    for name in wanted:
        src = src_root / name
        dst = dst_root / name
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        elif dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, symlinks=True)


def _restore_git_backups(dst_root: Path) -> None:
    for backup in dst_root.glob("*/git_backup"):
        git_dir = backup.parent / ".git"
        if not git_dir.exists():
            backup.rename(git_dir)


def _remove_copied_manager(dst_root: Path) -> None:
    # Use the current uv-pip Manager instead of loading a second copied
    # Manager implementation from the CNB / clone tree.
    for manager_name in ("comfyui-manager", "ComfyUI-Manager"):
        manager_dir = dst_root / manager_name
        if manager_dir.exists():
            shutil.rmtree(manager_dir)


# Unified uv-sync of 130 community nodes cannot satisfy every upstream pin.
# Live serve hit accelerate>=0.29.0,<0.32.0 vs >=1.6.0, then Pillow==10.3.0 vs
# >=10.4.0. Policy: keep lower bounds, convert == to >=, drop < / <=.
#
# Transitive metadata can still be unsatisfiable in one lock (YuE's
# descript-audiotools wants protobuf<3.20, IPAdapter-Flux wants protobuf>=4.25.5).
# Drop those packages from requirement files; remaining deps install sequentially
# like the CNB image (cm-cli / uv pip per node), not as one uv-sync solve.
_DROP_PACKAGES = frozenset(
    {
        "descript-audiotools",
        # Ashley image already ships the CUDA torch stack. Re-resolving these
        # from a node requirements.txt can replace the GPU wheels.
        "torch",
        "torchvision",
        "torchaudio",
        "torchao",
        "cuda-toolkit",
    }
)
_PKG_SPEC_RE = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[^\]]*\])?"
    r"(?P<spec>(?:\s*(?:===|==|!=|<=|>=|~=|<|>)\s*[^,;=\s\"']+"
    r"(?:\s*,\s*(?:===|==|!=|<=|>=|~=|<|>)\s*[^,;=\s\"']+)*))",
    re.IGNORECASE,
)
_CLAUSE_RE = re.compile(r"(===|==|!=|<=|>=|~=|<|>)\s*([^,;=\s\"']+)")
_REQUIREMENT_FILENAMES = (
    "requirements.txt",
    "requirements-lock.txt",
    "requirements.in",
    "pyproject.toml",
)


def _normalize_requirement_name(name: str) -> str:
    return name.replace("_", "-").casefold()


def _relax_spec(spec: str) -> str:
    """Return a PEP 508 specifier that only keeps lower / inequality bounds."""

    kept: list[str] = []
    for operator, version in _CLAUSE_RE.findall(spec):
        if operator in {"<", "<="}:
            continue
        if operator in {"==", "===", "~="}:
            operator = ">="
        kept.append(f"{operator}{version}")
    return ",".join(kept)


def _drop_blocked_packages(text: str) -> str:
    """Remove packages whose published metadata cannot coexist in this snapshot."""

    kept_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        token = line.split("#", 1)[0].strip().strip("\",'")
        name = re.split(r"[<>=!~\[\s;]", token, maxsplit=1)[0]
        if name and _normalize_requirement_name(name) in _DROP_PACKAGES:
            continue
        kept_lines.append(line)
    updated = "".join(kept_lines)
    for package in _DROP_PACKAGES:
        pattern = rf"""["']{re.escape(package)}[^"']*["']\s*,?\s*"""
        updated = re.sub(pattern, "", updated, flags=re.IGNORECASE)
        alt = package.replace("-", "_")
        if alt != package:
            pattern = rf"""["']{re.escape(alt)}[^"']*["']\s*,?\s*"""
            updated = re.sub(pattern, "", updated, flags=re.IGNORECASE)
    updated = re.sub(r",\s*,", ",", updated)
    updated = re.sub(r"\[\s*,", "[", updated)
    updated = re.sub(r",\s*\]", "]", updated)
    return updated


def _relax_requirement_text(text: str) -> str:
    """Rewrite package specs in requirements.txt / pyproject dependency text."""

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        if _normalize_requirement_name(name) in _DROP_PACKAGES:
            return ""
        relaxed = _relax_spec(match.group("spec"))
        extras = match.group("extras") or ""
        if not relaxed:
            return name + extras
        return f"{name}{extras}{relaxed}"

    return _PKG_SPEC_RE.sub(replace, _drop_blocked_packages(text))


def _relax_unsatisfiable_pins(dst_root: Path) -> list[str]:
    """Rewrite conflict-prone pins so sequential pip can stack the 130-node set."""

    patched: list[str] = []
    if not dst_root.is_dir():
        return patched
    for node_dir in sorted(dst_root.iterdir()):
        if not node_dir.is_dir():
            continue
        for filename in _REQUIREMENT_FILENAMES:
            path = node_dir / filename
            if not path.is_file():
                continue
            original = path.read_text(encoding="utf-8")
            updated = _relax_requirement_text(original)
            if updated != original:
                path.write_text(updated, encoding="utf-8")
                patched.append(f"{node_dir.name}/{filename}")
    return patched


def install_base_nodes(
    *,
    comfy_root: str = "/ComfyUI",
    source_custom_nodes: str | None = None,
    manifest_path: str = "/opt/comfy-base-nodes.json",
) -> None:
    """Install the pinned 130-node set into ``comfy_root`` and write a manifest.

    Production (no ``source_custom_nodes``): clone each GitHub URL from
    ``BASE_NODE_SOURCES`` into ``<comfy_root>/custom_nodes/<nodes.md name>``.

    Tests may pass ``source_custom_nodes`` to copy a local fixture tree instead.
    """

    wanted = list(BASE_NODE_NAMES)
    dst_root = Path(comfy_root) / "custom_nodes"

    if source_custom_nodes:
        _copy_base_nodes(Path(source_custom_nodes), dst_root, wanted)
        _restore_git_backups(dst_root)
    else:
        _clone_base_nodes(dst_root)

    _remove_copied_manager(dst_root)
    relaxed_pins = _relax_unsatisfiable_pins(dst_root)

    cloned = [
        {"name": name, "repository": url}
        for name, url in BASE_NODE_SOURCES
        if url is not None
    ]
    manifest = {
        "source": BASE_NODES_SOURCE,
        "repository": BASE_NODES_REPOSITORY,
        "image": BASE_NODES_IMAGE,
        "image_fallback": BASE_NODES_IMAGE_FALLBACK,
        "snapshot": BASE_NODES_SNAPSHOT,
        "count": len(wanted),
        "cloned": len(cloned),
        "nodes": wanted,
        "repositories": cloned,
        "relaxed_pins": relaxed_pins,
    }
    Path(manifest_path).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_base_nodes_commands(
    *,
    comfy_root: str = "/ComfyUI",
    python_bin: str = "/ComfyUI/venv/bin/python3",
    installer_path: str = INSTALLER_REMOTE_PATH,
) -> list[str]:
    """Return Modal Dockerfile-safe single-line shell steps for the base install.

    Each string is intended for a separate ``Image.run_commands`` entry. Do not
    embed heredocs or a giant ``python -c`` payload — Modal's Dockerfile parser
    rejects those forms.
    """

    q_py = shlex.quote(python_bin)
    q_installer = shlex.quote(installer_path)
    q_root = shlex.quote(comfy_root)

    # Keep askpass + clone in one RUN so GITHUB_TOKEN is available to git.
    clone_step = (
        "set -eu; "
        'if [ -n "${GITHUB_TOKEN:-}" ]; then '
        "printf '%s\\n' '#!/bin/sh' "
        "'case \"$1\" in *Username*) echo x-access-token ;; *) echo \"$GITHUB_TOKEN\" ;; esac' "
        "> /tmp/comfy-git-askpass && chmod 700 /tmp/comfy-git-askpass && "
        "export GIT_ASKPASS=/tmp/comfy-git-askpass GIT_TERMINAL_PROMPT=0; "
        "fi; "
        "set -x; "
        f"{q_py} {q_installer} --comfy-root {q_root}; "
        "rm -f /tmp/comfy-git-askpass"
    )

    # CNB installed nodes one-by-one with cm-cli/pip. A single `comfy node uv-sync`
    # cannot solve this 130-node set (direct pins and transitive protobuf wars).
    # Install each requirements.txt sequentially; one node failing must not
    # abort the image (same as the source image). git+ deps need askpass.
    deps_step = (
        "set -eu; "
        'if [ -n "${GITHUB_TOKEN:-}" ]; then '
        "printf '%s\\n' '#!/bin/sh' "
        "'case \"$1\" in *Username*) echo x-access-token ;; *) echo \"$GITHUB_TOKEN\" ;; esac' "
        "> /tmp/comfy-git-askpass && chmod 700 /tmp/comfy-git-askpass && "
        "export GIT_ASKPASS=/tmp/comfy-git-askpass GIT_TERMINAL_PROMPT=0; "
        "fi; "
        "fail=0; "
        "for req in /ComfyUI/custom_nodes/*/requirements.txt; do "
        'if [ -f "$req" ]; then '
        f"/ComfyUI/venv/bin/uv pip install --python {q_py} --no-cache -r \"$req\" || fail=$((fail+1)); "
        "fi; "
        "done; "
        "rm -f /tmp/comfy-git-askpass; "
        'echo "base-node requirement-file failures: $fail"'
    )

    return [
        clone_step,
        f"/usr/local/bin/uv pip install --python {q_py} --no-cache 'comfyui-manager==4.2.2'",
        deps_step,
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Install pinned CNB base custom nodes.")
    parser.add_argument("--comfy-root", default="/ComfyUI")
    parser.add_argument(
        "--source-custom-nodes",
        default=None,
        help="Copy from this local tree instead of cloning GitHub (tests / fixtures).",
    )
    parser.add_argument("--manifest-path", default="/opt/comfy-base-nodes.json")
    args = parser.parse_args(argv)
    install_base_nodes(
        comfy_root=args.comfy_root,
        source_custom_nodes=args.source_custom_nodes,
        manifest_path=args.manifest_path,
    )


if __name__ == "__main__":
    main()
