"""Pinned base custom-node distribution for the Modal ComfyUI image.

The desired node set is copied from a fixed ComfyUI-yi_dian_tong commit during
Modal Image build. It is intentionally not fetched from ``nodes.md`` at runtime.
"""

from __future__ import annotations

import json
import shlex

BASE_NODES_SOURCE = "https://cnb.cool/SKDZSS90/ComfyUI-yi_dian_tong/-/blob/main/nodes.md"
BASE_NODES_REPOSITORY = "https://cnb.cool/SKDZSS90/ComfyUI-yi_dian_tong.git"
BASE_NODES_SOURCE_REV = "5152c24cda53eddae02c0e8f0dab832444dab891"
BASE_NODES_SNAPSHOT = "2026-08-13"

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


def build_base_nodes_command(
    *,
    comfy_root: str = "/ComfyUI",
    python_bin: str = "/ComfyUI/venv/bin/python3",
) -> str:
    """Build the pinned 130-node base from the CNB source snapshot.

    The installer helper is written to a temp file via a quoted heredoc, then
    executed. Avoid embedding a giant ``python -c '...'`` payload: Modal wraps
    ``run_commands`` into Dockerfile ``RUN`` layers, and nested shell quoting of
    a large inline script breaks the image build parser.
    """

    payload = json.dumps(BASE_NODE_NAMES, ensure_ascii=False)
    py_script = f"""
import json
import shutil
from pathlib import Path

wanted = json.loads({payload!r})
src_root = Path('/tmp/comfy-base-source/ComfyUI/custom_nodes')
dst_root = Path({comfy_root!r}) / 'custom_nodes'
missing = [name for name in wanted if not (src_root / name).is_dir()]
if missing:
    raise SystemExit('Pinned CNB snapshot is missing expected custom nodes: ' + ', '.join(missing))

dst_root.mkdir(parents=True, exist_ok=True)
for name in wanted:
    src = src_root / name
    dst = dst_root / name
    if dst.is_symlink() or dst.is_file():
        dst.unlink()
    elif dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=True)

for backup in dst_root.glob('*/git_backup'):
    git_dir = backup.parent / '.git'
    if not git_dir.exists():
        backup.rename(git_dir)

# Use the current pip-distributed Manager instead of loading a second copied
# Manager implementation from the CNB tree.
for manager_name in ('comfyui-manager', 'ComfyUI-Manager'):
    manager_dir = dst_root / manager_name
    if manager_dir.exists():
        shutil.rmtree(manager_dir)

manifest = {{
    'source': {BASE_NODES_SOURCE!r},
    'repository': {BASE_NODES_REPOSITORY!r},
    'revision': {BASE_NODES_SOURCE_REV!r},
    'snapshot': {BASE_NODES_SNAPSHOT!r},
    'count': len(wanted),
    'nodes': wanted,
}}
Path('/opt/comfy-base-nodes.json').write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False) + '\\n', encoding='utf-8'
)
""".strip()

    q_repo = shlex.quote(BASE_NODES_REPOSITORY)
    q_rev = shlex.quote(BASE_NODES_SOURCE_REV)
    q_py = shlex.quote(python_bin)
    helper_path = "/tmp/install_base_nodes.py"

    # Multi-line shell (not "; "-joined) so the heredoc stays Modal/Dockerfile-safe.
    return f"""set -eu
rm -rf /tmp/comfy-base-source
git init -q /tmp/comfy-base-source
git -C /tmp/comfy-base-source remote add origin {q_repo}
git -C /tmp/comfy-base-source config core.sparseCheckout true
printf 'ComfyUI/custom_nodes/\\n' > /tmp/comfy-base-source/.git/info/sparse-checkout
git -C /tmp/comfy-base-source fetch -q --filter=blob:none --depth=1 origin {q_rev} || git -C /tmp/comfy-base-source fetch -q --filter=blob:none --depth=500 origin main
git -C /tmp/comfy-base-source cat-file -e {q_rev}^{{commit}}
git -C /tmp/comfy-base-source checkout -q --detach {q_rev}
cat > {helper_path} <<'COMFY_BASE_NODES_PY'
{py_script}
COMFY_BASE_NODES_PY
{q_py} {helper_path}
rm -rf /tmp/comfy-base-source {helper_path}
{q_py} -m pip install --no-cache-dir 'comfy-cli==1.12.0' 'comfyui-manager==4.2.2' uv
COMFY_NO_TELEMETRY=1 /ComfyUI/venv/bin/comfy --workspace=/ComfyUI node uv-sync
"""
