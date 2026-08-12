"""Pinned base custom-node distribution for the Modal ComfyUI image.

The desired node set is copied from a fixed ComfyUI-yi_dian_tong commit during
Modal Image build. It is intentionally not fetched from ``nodes.md`` at runtime.

This module is also the image-build installer: ``comfyui_modal.py`` copies it into
the image via ``Image.add_local_file(..., copy=True)`` and runs it with the
Ashley venv Python. Modal wraps ``run_commands`` into Dockerfile ``RUN`` layers
and does not support shell heredocs or giant nested ``python -c`` payloads.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
from pathlib import Path

BASE_NODES_SOURCE = "https://cnb.cool/SKDZSS90/ComfyUI-yi_dian_tong/-/blob/main/nodes.md"
BASE_NODES_REPOSITORY = "https://cnb.cool/SKDZSS90/ComfyUI-yi_dian_tong.git"
BASE_NODES_SOURCE_REV = "5152c24cda53eddae02c0e8f0dab832444dab891"
BASE_NODES_SNAPSHOT = "2026-08-13"

# Path where comfyui_modal.py places this file inside the build image.
INSTALLER_REMOTE_PATH = "/opt/comfy-base-nodes/base_nodes.py"

BASE_NODE_NAMES: tuple[str, ...] = (
    'a-person-mask-generator',
    'audio-separation-nodes-comfyui',
    'cg-image-filter',
    'comfy-mtb',
    'ComfyLiterals',
    'ComfyMath',
    'ComfyQR',
    'ComfyUI_ADV_CLIP_emb',
    'ComfyUI_AdvancedRefluxControl',
    'Comfyui_Comfly',
    'ComfyUI_Comfyroll_CustomNodes',
    'comfyui_controlnet_aux',
    'comfyui_custom_nodes_alekpet',
    'comfyui_essentials',
    'comfyui_facesimilarity',
    'ComfyUI_Fill-Nodes',
    'ComfyUI_FizzNodes',
    'comfyui_instantid',
    'comfyui_ipadapter_plus',
    'ComfyUI_LayerStyle_Advance',
    'ComfyUI_LayerStyle',
    'Comfyui_LG_Tools',
    'ComfyUi_NNLatentUpscale',
    'comfyui_patches_ll',
    'Comfyui_PDuse',
    'comfyui_pops',
    'comfyui_prompt_assistant',
    'comfyui_pulid_flux_ll',
    'comfyui_segment_anything',
    'comfyui_slk_joy_caption_two',
    'ComfyUI_Sonic',
    'ComfyUI_Text_Translation',
    'comfyui_ttp_toolset',
    'comfyui_ultimatesdupscale',
    'ComfyUI_YuE',
    'ComfyUI-AnimateDiff-Evolved',
    'ComfyUI-Anyline',
    'comfyui-art-venture',
    'ComfyUI-AutoCropFaces',
    'ComfyUI-Basic-Math',
    'comfyui-browser',
    'comfyui-brushnet',
    'ComfyUI-Crystools',
    'comfyui-custom-scripts',
    'ComfyUI-DD-Translation',
    'comfyui-depthanythingv2',
    'comfyui-detail-daemon',
    'ComfyUI-Easy-Use',
    'ComfyUI-Embedding_Picker',
    'ComfyUI-fastblend',
    'comfyui-fitsize',
    'ComfyUI-FlashVSR_Ultra_Fast',
    'comfyui-florence2',
    'comfyui-frame-interpolation',
    'ComfyUI-FramePackWrapper',
    'ComfyUI-GGUF',
    'ComfyUI-GIMM-VFI',
    'ComfyUI-GlifNodes',
    'ComfyUI-GLM4',
    'ComfyUI-GradientBlur',
    'ComfyUI-HunyuanVideoWrapper',
    'comfyui-ic-light-native',
    'ComfyUI-IC-Light',
    'comfyui-imagesubfolders',
    'ComfyUI-Impact-Pack',
    'comfyui-impact-subpack',
    'comfyui-in-context-lora-utils',
    'comfyui-inpaint-cropandstitch',
    'comfyui-inpaint-nodes',
    'comfyui-inspire-pack',
    'comfyui-inspyrenet-rembg',
    'ComfyUI-IPAdapter-Flux',
    'ComfyUI-KJNodes',
    'comfyui-lama-remover',
    'comfyui-layerdiffuse',
    'comfyui-ltxvideolora',
    'comfyui-lumi-batcher',
    'comfyui-manager',
    'ComfyUI-Marigold',
    'ComfyUI-MelBandRoFormer',
    'ComfyUI-MingNodes',
    'comfyui-mixlab-nodes',
    'comfyui-openai-fm',
    'comfyui-openpose-editor',
    'ComfyUI-Ovi',
    'comfyui-post-processing-nodes',
    'ComfyUi-RadarWeightNode',
    'ComfyUI-ReActor',
    'comfyui-redux-prompt',
    'ComfyUI-RMBG',
    'comfyui-saveimage-plus',
    'Comfyui-SecNodes',
    'ComfyUI-SeedVR2_VideoUpscaler',
    'ComfyUI-segment-anything-2',
    'ComfyUI-SoundFlow',
    'comfyui-stringsandthings',
    'comfyui-supir',
    'comfyui-tensorops',
    'ComfyUI-Tripo',
    'ComfyUI-UVR5',
    'comfyui-various',
    'comfyui-video-matting',
    'ComfyUI-VideoBasic',
    'ComfyUI-VideoHelperSuite',
    'ComfyUI-WanAnimatePreprocess',
    'ComfyUI-WanStartEndFramesNative',
    'ComfyUI-WanVideoStartEndFrames',
    'ComfyUI-WanVideoWrapper',
    'comfyui-wd14-tagger',
    'ComfyUI-YCNodes',
    'D2-SavePSD-ComfyUI',
    'efficiency-nodes-comfyui',
    'flux-prompt-generator',
    'images_base64',
    'janus-pro',
    'joycaption_comfyui',
    'komojini-comfyui-nodes',
    'mikey_nodes',
    'OneButtonPrompt',
    'portraittools-mw',
    'pulid_comfyui',
    'rembg-comfyui-node-better',
    'rgthree-comfy',
    'skimmed_cfg',
    'stability-ComfyUI-nodes',
    'teacache',
    'wanblockswap',
    'was-node-suite-comfyui',
    'wavespeed',
    'x-flux-comfyui',
)

BASE_NODE_COUNT = len(BASE_NODE_NAMES)
assert BASE_NODE_COUNT == 130
assert len(set(BASE_NODE_NAMES)) == BASE_NODE_COUNT


def install_base_nodes(
    *,
    comfy_root: str = "/ComfyUI",
    source_custom_nodes: str = "/tmp/comfy-base-source/ComfyUI/custom_nodes",
    manifest_path: str = "/opt/comfy-base-nodes.json",
) -> None:
    """Copy the pinned CNB custom-node set into ``comfy_root`` and write a manifest.

    Assumes the sparse-checkout of ``BASE_NODES_REPOSITORY`` at
    ``BASE_NODES_SOURCE_REV`` is already present under ``/tmp/comfy-base-source``.
    """

    wanted = list(BASE_NODE_NAMES)
    src_root = Path(source_custom_nodes)
    dst_root = Path(comfy_root) / "custom_nodes"
    missing = [name for name in wanted if not (src_root / name).is_dir()]
    if missing:
        raise SystemExit(
            "Pinned CNB snapshot is missing expected custom nodes: " + ", ".join(missing)
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

    for backup in dst_root.glob("*/git_backup"):
        git_dir = backup.parent / ".git"
        if not git_dir.exists():
            backup.rename(git_dir)

    # Use the current pip-distributed Manager instead of loading a second copied
    # Manager implementation from the CNB tree.
    for manager_name in ("comfyui-manager", "ComfyUI-Manager"):
        manager_dir = dst_root / manager_name
        if manager_dir.exists():
            shutil.rmtree(manager_dir)

    manifest = {
        "source": BASE_NODES_SOURCE,
        "repository": BASE_NODES_REPOSITORY,
        "revision": BASE_NODES_SOURCE_REV,
        "snapshot": BASE_NODES_SNAPSHOT,
        "count": len(wanted),
        "nodes": wanted,
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

    q_repo = shlex.quote(BASE_NODES_REPOSITORY)
    q_rev = shlex.quote(BASE_NODES_SOURCE_REV)
    q_py = shlex.quote(python_bin)
    q_installer = shlex.quote(installer_path)
    q_root = shlex.quote(comfy_root)

    return [
        "rm -rf /tmp/comfy-base-source",
        "git init -q /tmp/comfy-base-source",
        f"git -C /tmp/comfy-base-source remote add origin {q_repo}",
        "git -C /tmp/comfy-base-source config core.sparseCheckout true",
        "printf 'ComfyUI/custom_nodes/\\n' > /tmp/comfy-base-source/.git/info/sparse-checkout",
        (
            f"git -C /tmp/comfy-base-source fetch -q --filter=blob:none --depth=1 origin {q_rev} "
            "|| git -C /tmp/comfy-base-source fetch -q --filter=blob:none --depth=500 origin main"
        ),
        f"git -C /tmp/comfy-base-source cat-file -e {q_rev}^{{commit}}",
        f"git -C /tmp/comfy-base-source checkout -q --detach {q_rev}",
        f"{q_py} {q_installer} --comfy-root {q_root}",
        "rm -rf /tmp/comfy-base-source",
        f"{q_py} -m pip install --no-cache-dir 'comfy-cli==1.12.0' 'comfyui-manager==4.2.2' uv",
        "COMFY_NO_TELEMETRY=1 /ComfyUI/venv/bin/comfy --workspace=/ComfyUI node uv-sync",
    ]


def build_base_nodes_command(
    *,
    comfy_root: str = "/ComfyUI",
    python_bin: str = "/ComfyUI/venv/bin/python3",
    installer_path: str = INSTALLER_REMOTE_PATH,
) -> str:
    """Join Modal-safe steps for tests / inspection (prefer ``build_base_nodes_commands``)."""

    return "\n".join(
        build_base_nodes_commands(
            comfy_root=comfy_root,
            python_bin=python_bin,
            installer_path=installer_path,
        )
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Install pinned CNB base custom nodes.")
    parser.add_argument("--comfy-root", default="/ComfyUI")
    parser.add_argument(
        "--source-custom-nodes",
        default="/tmp/comfy-base-source/ComfyUI/custom_nodes",
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
