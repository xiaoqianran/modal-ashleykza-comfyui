from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class ModelAsset:
    url: str
    filename: str | None = None
    sha256: str | None = None
    extract: bool = False


@dataclass(frozen=True)
class NodeRecipe:
    repo: str
    name: str | None = None
    ref: str | None = None
    recursive: bool = False
    requirements: tuple[str, ...] = ()
    pip: tuple[str, ...] = ()
    pre_commands: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()


@dataclass(frozen=True)
class Profile:
    model_packs: tuple[str, ...] = ()
    node_packs: tuple[str, ...] = ()
    comfy_args: tuple[str, ...] = ()
    description: str = ""


def M(url: str, *, filename: str | None = None, sha256: str | None = None, extract: bool = False) -> ModelAsset:
    return ModelAsset(url=url, filename=filename, sha256=sha256, extract=extract)


def N(
    repo: str,
    *,
    name: str | None = None,
    ref: str | None = None,
    recursive: bool = False,
    requirements: Sequence[str] = (),
    pip: Sequence[str] = (),
    pre_commands: Sequence[str] = (),
    commands: Sequence[str] = (),
) -> NodeRecipe:
    if name is None:
        name = PurePosixPath(repo.rstrip("/")).name.removesuffix(".git")
    return NodeRecipe(
        repo=repo,
        name=name,
        ref=ref,
        recursive=recursive,
        requirements=tuple(requirements),
        pip=tuple(pip),
        pre_commands=tuple(pre_commands),
        commands=tuple(commands),
    )


MODEL_DIRS = (
    "checkpoints", "clip", "clip_vision", "controlnet", "diffusion_models",
    "embeddings", "gligen", "hypernetworks", "latent_upscale_models", "loras",
    "photomaker", "style_models", "text_encoders", "unet", "upscale_models",
    "vae", "vae_approx", "background_removal", "Pixal3D", "geometry_estimation",
    "model_patches", "audio_encoders", "detection", "frame_interpolation",
    "optical_flow", "cosmos3", "microsoft", "facebook",
)


MODEL_PACKS: Mapping[str, Mapping[str, tuple[ModelAsset, ...]]] = {
    "ltx23": {
        "checkpoints": (M("https://huggingface.co/Lightricks/LTX-2.3-fp8/resolve/main/ltx-2.3-22b-dev-fp8.safetensors"),),
        "text_encoders": (M("https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors"),),
        "loras": (M("https://huggingface.co/Lightricks/LTX-2.3/resolve/main/ltx-2.3-22b-distilled-lora-384.safetensors"),),
        "latent_upscale_models": (M("https://huggingface.co/Lightricks/LTX-2.3/resolve/main/ltx-2.3-spatial-upscaler-x2-1.1.safetensors"),),
    },
    "nordy-kontext-views": {
        "diffusion_models": (M("https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev/resolve/main/flux1-kontext-dev.safetensors"),),
        "text_encoders": (M("https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors"),),
        "upscale_models": (
            M("https://huggingface.co/Akumetsu971/SD_Anime_Futuristic_Armor/resolve/main/4x_NMKD-Siax_200k.pth"),
        ),
        "loras": (
            M("https://civitai.com/api/download/models/1956822?type=Model&format=SafeTensor"),
            M("https://huggingface.co/saquiboye/omini-kontext/resolve/main/spatial-character-test.safetensors"),
        ),
    },
    "nordy-clothes": {
        "clip_vision": (M("https://huggingface.co/Comfy-Org/sigclip_vision_384/resolve/main/sigclip_vision_patch14_384.safetensors"),),
        "diffusion_models": (M("https://huggingface.co/mp3pintyo/FLUX.1/resolve/main/flux1-fill-dev.safetensors"),),
        "style_models": (M("https://huggingface.co/camenduru/FLUX.1-dev/resolve/fc63f3204a12362f98c04bc4c981a06eb9123eee/flux1-redux-dev.safetensors"),),
        "text_encoders": (
            M("https://huggingface.co/zer0int/CLIP-GmP-ViT-L-14/resolve/main/ViT-L-14-BEST-smooth-GmP-TE-only-HF-format.safetensors"),
            M("https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors"),
        ),
        "vae": (M("https://huggingface.co/lovis93/testllm/resolve/ed9cf1af7465cebca4649157f118e331cf2a084f/ae.safetensors"),),
        "loras": (
            M("https://huggingface.co/TTPlanet/Migration_Lora_flux/resolve/main/Migration_Lora_cloth.safetensors"),
            M("https://huggingface.co/ali-vilab/ACE_Plus/resolve/main/subject/comfyui_subject_lora16.safetensors"),
        ),
    },
    "qwen-image": {
        "diffusion_models": (M("https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_fp8_e4m3fn.safetensors"),),
        "text_encoders": (M("https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"),),
        "vae": (M("https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors"),),
    },
    "flux-krea": {
        "diffusion_models": (M("https://huggingface.co/Comfy-Org/FLUX.1-Krea-dev_ComfyUI/resolve/main/split_files/diffusion_models/flux1-krea-dev_fp8_scaled.safetensors"),),
        "text_encoders": (
            M("https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors"),
            M("https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors"),
        ),
        "vae": (M("https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors"),),
    },
    "flux-kontext": {
        "diffusion_models": (M("https://huggingface.co/Comfy-Org/flux1-kontext-dev_ComfyUI/resolve/main/split_files/diffusion_models/flux1-dev-kontext_fp8_scaled.safetensors"),),
        "text_encoders": (M("https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn_scaled.safetensors"),),
        "vae": (M("https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors"),),
    },
    "wan22": {
        "clip_vision": (
            M("https://huggingface.co/Kijai/WanVideo_comfy/resolve/b4fde5290d401dff216d70a915643411e9532951/open-clip-xlm-roberta-large-vit-huge-14_fp16.safetensors"),
            M("https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/clip_vision/clip_vision_h.safetensors"),
        ),
        "diffusion_models": (
            M("https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"),
            M("https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"),
            M("https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"),
            M("https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors"),
            M("https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled/resolve/main/I2V/Wan2_2-I2V-A14B-HIGH_fp8_e4m3fn_scaled_KJ.safetensors"),
            M("https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled/resolve/main/I2V/Wan2_2-I2V-A14B-LOW_fp8_e4m3fn_scaled_KJ.safetensors"),
            M("https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled/resolve/main/T2V/Wan2_2-T2V-A14B-LOW_fp8_e4m3fn_scaled_KJ.safetensors"),
            M("https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled/resolve/main/T2V/Wan2_2-T2V-A14B_HIGH_fp8_e4m3fn_scaled_KJ.safetensors"),
        ),
        "text_encoders": (
            M("https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
            M("https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors"),
            M("https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors"),
            M("https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/umt5-xxl-enc-bf16.safetensors"),
        ),
        "vae": (
            M("https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors"),
            M("https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors"),
            M("https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Wan2_1_VAE_bf16.safetensors"),
        ),
        "unet": (M("https://huggingface.co/Phr00t/WAN2.2-14B-Rapid-AllInOne/resolve/main/wan2.2-i2v-rapid-aio.safetensors"),),
        "loras": (
            M("https://huggingface.co/lightx2v/Wan2.1-I2V-14B-480P-StepDistill-CfgDistill-Lightx2v/resolve/main/loras/Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors"),
            M("https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Wan21_T2V_14B_lightx2v_cfg_step_distill_lora_rank32.safetensors"),
            M("https://huggingface.co/metercai/SimpleSDXL2/resolve/e9b400accd5dbd15517e47c7490e1783f4c42c42/SimpleModels/loras/WAN2.1_SmartphoneSnapshotPhotoReality_v1_by-AI_Characters.safetensors"),
            M("https://huggingface.co/vrgamedevgirl84/Wan14BT2VFusioniX/resolve/main/FusionX_LoRa/Wan2.1_T2V_14B_FusionX_LoRA.safetensors"),
            M("https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Lightx2v/lightx2v_I2V_14B_480p_cfg_step_distill_rank128_bf16.safetensors"),
            M("https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Wan22-Lightning/Wan2.2-Lightning_T2V-A14B-4steps-lora_HIGH_fp16.safetensors"),
            M("https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Wan22-Lightning/Wan2.2-Lightning_T2V-A14B-4steps-lora_LOW_fp16.safetensors"),
        ),
    },
}


# Extra nodes only — the 130 GitHub base clones already cover Wan/KJ/VHS/GGUF/Manager.
NODE_PACKS: Mapping[str, tuple[NodeRecipe, ...]] = {
    "nordy-clothes-extra": (
        N("https://github.com/chrisgoringe/cg-use-everywhere.git"),
        N("https://github.com/TinyTerra/ComfyUI_tinyterraNodes.git"),
    ),
    "qwen-image-extra": (
        N("https://github.com/HM-RunningHub/ComfyUI_RH_Qwen-Image.git", requirements=("requirements.txt",)),
    ),
    "flux-kontext-extra": (
        N("https://github.com/Saquib764/omini-kontext.git", requirements=("requirements.txt",)),
    ),
    "wan-notebook-extra": (
        N("https://github.com/chrisgoringe/cg-use-everywhere.git"),
        N("https://github.com/al-swaiti/ComfyUI-OllamaGemini.git", requirements=("requirements.txt",)),
        N("https://github.com/ClownsharkBatwing/RES4LYF", requirements=("requirements.txt",)),
        N("https://github.com/Kosinkadink/ComfyUI-Advanced-ControlNet.git"),
        N("https://github.com/aiaiaikkk/ComfyUI-Curve.git", requirements=("requirements.txt",)),
    ),
    "nunchaku": (
        N("https://github.com/nunchaku-tech/ComfyUI-nunchaku.git", requirements=("requirements.txt",)),
    ),
}


PROFILES: Mapping[str, Profile] = {
    "base": Profile(
        description="Ashley runtime only; 130 GitHub base nodes need COMFY_BASE_NODES=1."
    ),
    "ltx23": Profile(
        model_packs=("ltx23",),
        description="LTX 2.3 model pack. Wan/KJ-style nodes are not included unless COMFY_BASE_NODES=1.",
    ),
    "nordy-kontext-views": Profile(
        model_packs=("nordy-kontext-views",),
        node_packs=("flux-kontext-extra",),
        description="Nordy/FLUX Kontext multi-view recipe.",
    ),
    "nordy-clothes": Profile(
        model_packs=("nordy-clothes",),
        node_packs=("nordy-clothes-extra",),
        description="Nordy clothing/inpaint recipe; only two nodes are extra beyond base.",
    ),
    "qwen-image": Profile(
        model_packs=("qwen-image",),
        node_packs=("qwen-image-extra",),
        comfy_args=("--preview-method", "auto"),
        description="Qwen Image + RunningHub node on the common base.",
    ),
    "flux-krea": Profile(model_packs=("flux-krea",), description="FLUX.1 Krea model pack."),
    "flux-kontext": Profile(
        model_packs=("flux-kontext",),
        node_packs=("flux-kontext-extra",),
        description="FLUX Kontext + omini-kontext on the common base.",
    ),
    "wan22": Profile(
        model_packs=("wan22",),
        comfy_args=("--preview-method", "auto"),
        description="Wan 2.2 models. Wan/KJ/VHS/GGUF nodes need COMFY_BASE_NODES=1.",
    ),
    "wan22-notebook-full": Profile(
        model_packs=("wan22",),
        node_packs=("wan-notebook-extra",),
        comfy_args=("--preview-method", "auto"),
        description="Wan 2.2 plus the few notebook nodes absent from the common base.",
    ),
    "nunchaku": Profile(node_packs=("nunchaku",), description="Nunchaku custom node beyond the common base."),
}


def get_profile(name: str) -> Profile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        available = ", ".join(sorted(PROFILES))
        raise KeyError(f"Unknown profile {name!r}. Available: {available}") from exc
