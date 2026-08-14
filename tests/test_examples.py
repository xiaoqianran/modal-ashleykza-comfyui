import importlib.util
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse

import recipes
import workflow_resolver
from comfy_engine import normalize_huggingface_url

ROOT = Path(__file__).resolve().parents[1]
CIVITAI_ID = re.compile(r"/models/\d+")


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ExampleLockTests(unittest.TestCase):
    def test_z_image_lock_matches_resolve(self):
        source = ROOT / "examples" / "z-image-base.json"
        lock_path = ROOT / "examples" / "z-image-base.lock.json"
        resolved = workflow_resolver.resolve_workflow(source)
        committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
        self.assertEqual(
            {(m["category"], m["filename"]) for m in resolved["models"]},
            {(m["category"], m["filename"]) for m in committed["models"]},
        )
        self.assertTrue(workflow_resolver.lock_matches_workflow(committed, source))

    def test_triposplat_lock_matches_resolve(self):
        source = ROOT / "examples" / "triposplat-image-to-gaussian-splat.json"
        lock_path = ROOT / "examples" / "triposplat-image-to-gaussian-splat.lock.json"
        resolved = workflow_resolver.resolve_workflow(source)
        committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
        self.assertEqual(resolved["unresolved"], [])
        self.assertEqual(committed["unresolved"], [])
        self.assertEqual(committed["custom_nodes"], [])
        self.assertTrue(workflow_resolver.lock_matches_workflow(committed, source))
        self.assertEqual(
            {(m["category"], m["filename"]) for m in resolved["models"]},
            {(m["category"], m["filename"]) for m in committed["models"]},
        )
        names = {(m["category"], m["filename"]) for m in committed["models"]}
        self.assertIn(("background_removal", "birefnet.safetensors"), names)
        self.assertIn(("diffusion_models", "triposplat_fp16.safetensors"), names)
        self.assertIn("background_removal", recipes.MODEL_DIRS)

    def test_pixal3d_lock_is_curated_and_matches_workflow_hash(self):
        source = ROOT / "examples" / "pixal3d-image-to-3d.json"
        lock_path = ROOT / "examples" / "pixal3d-image-to-3d.lock.json"
        committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
        self.assertTrue(workflow_resolver.lock_matches_workflow(committed, source))
        self.assertEqual(committed["unresolved"], [])
        ids = {node["id"] for node in committed["custom_nodes"]}
        self.assertIn("Pixal3D-ComfyUI", ids)
        self.assertIn("comfyui-custom-scripts", ids)
        pixal = next(node for node in committed["custom_nodes"] if node["id"] == "Pixal3D-ComfyUI")
        self.assertEqual(pixal.get("version"), "0.2.4")
        self.assertNotIn("url", pixal)
        names = {(m["category"], m["filename"]) for m in committed["models"]}
        self.assertIn(("Pixal3D", "TencentARC_Pixal3D/pipeline.json"), names)
        self.assertIn(("Pixal3D", "briaai_RMBG-2.0/model.safetensors"), names)
        self.assertIn(("geometry_estimation", "moge_2_vitl_normal_fp16.safetensors"), names)
        self.assertIn("Pixal3D", recipes.MODEL_DIRS)
        self.assertIn("geometry_estimation", recipes.MODEL_DIRS)
        reused, origin = workflow_resolver.select_workflow_lock(source, lock_path)
        self.assertEqual(origin, "reused")
        self.assertEqual(len(reused["models"]), len(committed["models"]))

    def test_hunyuan3d_lock_matches_resolve(self):
        source = ROOT / "examples" / "hunyuan3d-2.1-image-to-3d.json"
        lock_path = ROOT / "examples" / "hunyuan3d-2.1-image-to-3d.lock.json"
        resolved = workflow_resolver.resolve_workflow(source)
        committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
        self.assertEqual(resolved["unresolved"], [])
        self.assertEqual(committed["custom_nodes"], [])
        self.assertTrue(workflow_resolver.lock_matches_workflow(committed, source))
        names = {(m["category"], m["filename"]) for m in committed["models"]}
        self.assertEqual(
            {(m["category"], m["filename"]) for m in resolved["models"]},
            names,
        )
        self.assertIn(("checkpoints", "hunyuan_3d_v2.1.safetensors"), names)
        text = source.read_text(encoding="utf-8")
        self.assertIn("ImageOnlyCheckpointLoader", text)
        self.assertIn("VAEDecodeHunyuan3D", text)
        self.assertIn("SaveGLB", text)
        self.assertIn("LoadImage", text)
        self.assertIn("mesh/Hunyuan3D_studio", text)

    def test_trellis2_lock_is_curated_and_matches_workflow_hash(self):
        source = ROOT / "examples" / "trellis2-image-to-3d.json"
        lock_path = ROOT / "examples" / "trellis2-image-to-3d.lock.json"
        committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
        self.assertTrue(workflow_resolver.lock_matches_workflow(committed, source))
        self.assertEqual(committed["unresolved"], [])
        self.assertEqual(len(committed["custom_nodes"]), 1)
        node = committed["custom_nodes"][0]
        self.assertEqual(node["id"], "ComfyUI-Trellis2")
        self.assertEqual(node["version"], "main")
        self.assertEqual(node["url"], "https://github.com/visualbruno/ComfyUI-Trellis2.git")
        names = {(m["category"], m["filename"]) for m in committed["models"]}
        self.assertIn(("microsoft", "TRELLIS.2-4B/pipeline.json"), names)
        self.assertIn(
            ("microsoft", "TRELLIS-image-large/ckpts/ss_dec_conv3d_16l8_fp16.safetensors"),
            names,
        )
        self.assertIn(
            ("facebook", "dinov3-vitl16-pretrain-lvd1689m/model.safetensors"),
            names,
        )
        self.assertIn("microsoft", recipes.MODEL_DIRS)
        self.assertIn("facebook", recipes.MODEL_DIRS)
        urls = {m["filename"]: m["url"] for m in committed["models"]}
        self.assertIn("visualbruno/dinov3-vitl16-pretrain-lvd1689m", urls[
            "dinov3-vitl16-pretrain-lvd1689m/model.safetensors"
        ])
        text = source.read_text(encoding="utf-8")
        self.assertIn('"type": "LoadImage"', text)
        self.assertNotIn("Trellis2LoadImageWithTransparency", text)
        self.assertIn("Trellis2LoadModel", text)
        self.assertIn("Trellis2ExportMesh", text)
        reused, origin = workflow_resolver.select_workflow_lock(source, lock_path)
        self.assertEqual(origin, "reused")
        self.assertEqual(len(reused["models"]), len(committed["models"]))

    def test_flux2_lock_matches_resolve(self):
        source = ROOT / "examples" / "flux2-dev-t2i.json"
        lock_path = ROOT / "examples" / "flux2-dev-t2i.lock.json"
        resolved = workflow_resolver.resolve_workflow(source)
        committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
        self.assertEqual(resolved["unresolved"], [])
        self.assertEqual(committed["custom_nodes"], [])
        self.assertTrue(workflow_resolver.lock_matches_workflow(committed, source))
        names = {(m["category"], m["filename"]) for m in committed["models"]}
        self.assertIn(("diffusion_models", "flux2_dev_fp8mixed.safetensors"), names)
        self.assertIn(("text_encoders", "mistral_3_small_flux2_bf16.safetensors"), names)
        self.assertIn(("vae", "full_encoder_small_decoder.safetensors"), names)

    def test_z_image_turbo_lock_matches_resolve(self):
        source = ROOT / "examples" / "z-image-turbo-t2i.json"
        lock_path = ROOT / "examples" / "z-image-turbo-t2i.lock.json"
        resolved = workflow_resolver.resolve_workflow(source)
        committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
        self.assertEqual(resolved["unresolved"], [])
        self.assertEqual(committed["custom_nodes"], [])
        self.assertTrue(workflow_resolver.lock_matches_workflow(committed, source))
        names = {(m["category"], m["filename"]) for m in committed["models"]}
        self.assertEqual(
            {(m["category"], m["filename"]) for m in resolved["models"]},
            names,
        )
        self.assertIn(("diffusion_models", "z_image_turbo_bf16.safetensors"), names)
        self.assertIn(("text_encoders", "qwen_3_4b.safetensors"), names)
        self.assertIn(("vae", "ae.safetensors"), names)

    def test_ideogram4_lock_is_curated_and_matches_workflow_hash(self):
        source = ROOT / "examples" / "ideogram4-t2i.json"
        lock_path = ROOT / "examples" / "ideogram4-t2i.lock.json"
        resolved = workflow_resolver.resolve_workflow(source)
        committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
        self.assertEqual(committed["unresolved"], [])
        self.assertEqual(committed["custom_nodes"], [])
        self.assertTrue(workflow_resolver.lock_matches_workflow(committed, source))
        resolved_names = {(m["category"], m["filename"]) for m in resolved["models"]}
        committed_names = {(m["category"], m["filename"]) for m in committed["models"]}
        self.assertTrue(resolved_names.issubset(committed_names))
        self.assertIn(("diffusion_models", "ideogram4_fp8_scaled.safetensors"), committed_names)
        self.assertIn(
            ("diffusion_models", "ideogram4_unconditional_fp8_scaled.safetensors"),
            committed_names,
        )
        self.assertIn(("text_encoders", "qwen3vl_8b_fp8_scaled.safetensors"), committed_names)
        self.assertIn(("text_encoders", "gemma4_e4b_it_fp8_scaled.safetensors"), committed_names)
        self.assertIn(("vae", "flux2-vae.safetensors"), committed_names)
        self.assertNotIn(("text_encoders", "gemma4_e4b_it_fp8_scaled.safetensors"), resolved_names)
        reused, origin = workflow_resolver.select_workflow_lock(source, lock_path)
        self.assertEqual(origin, "reused")
        self.assertEqual(len(reused["models"]), len(committed["models"]))

    def test_krea2_turbo_lock_matches_resolve(self):
        source = ROOT / "examples" / "krea2-turbo-t2i.json"
        lock_path = ROOT / "examples" / "krea2-turbo-t2i.lock.json"
        resolved = workflow_resolver.resolve_workflow(source)
        committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
        self.assertEqual(resolved["unresolved"], [])
        self.assertEqual(committed["custom_nodes"], [])
        self.assertTrue(workflow_resolver.lock_matches_workflow(committed, source))
        names = {(m["category"], m["filename"]) for m in committed["models"]}
        self.assertIn(("diffusion_models", "krea2_turbo_fp8_scaled.safetensors"), names)
        self.assertIn(("text_encoders", "qwen3vl_4b_fp8_scaled.safetensors"), names)
        self.assertIn(("vae", "qwen_image_vae.safetensors"), names)

    def test_qwen_image_2512_lock_matches_resolve(self):
        source = ROOT / "examples" / "qwen-image-2512.json"
        lock_path = ROOT / "examples" / "qwen-image-2512.lock.json"
        resolved = workflow_resolver.resolve_workflow(source)
        committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
        self.assertEqual(resolved["unresolved"], [])
        self.assertEqual(committed["custom_nodes"], [])
        self.assertTrue(workflow_resolver.lock_matches_workflow(committed, source))
        names = {(m["category"], m["filename"]) for m in committed["models"]}
        self.assertIn(("diffusion_models", "qwen_image_2512_fp8_e4m3fn.safetensors"), names)
        self.assertIn(("text_encoders", "qwen_2.5_vl_7b_fp8_scaled.safetensors"), names)

    def test_qwen_image_2512_lightning_lock_matches_resolve(self):
        source = ROOT / "examples" / "qwen-image-2512-lightning.json"
        lock_path = ROOT / "examples" / "qwen-image-2512-lightning.lock.json"
        resolved = workflow_resolver.resolve_workflow(source)
        committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
        self.assertEqual(resolved["unresolved"], [])
        self.assertEqual(committed["custom_nodes"], [])
        self.assertTrue(workflow_resolver.lock_matches_workflow(committed, source))
        names = {(m["category"], m["filename"]) for m in committed["models"]}
        self.assertEqual(
            {(m["category"], m["filename"]) for m in resolved["models"]},
            names,
        )
        self.assertIn(("diffusion_models", "qwen_image_2512_fp8_e4m3fn.safetensors"), names)
        self.assertIn(
            ("loras", "Qwen-Image-2512-Lightning-8steps-V1.0-fp32.safetensors"),
            names,
        )
        self.assertNotIn(
            ("loras", "Qwen-Image-2512-Lightning-4steps-V1.0-fp32.safetensors"),
            names,
        )
        text = source.read_text(encoding="utf-8")
        self.assertIn('"Enable 8 Steps LoRA?"', text)
        self.assertIn("enable_turbo_mode", text)

    def test_cosmos3_locks_are_curated_and_match_workflow_hash(self):
        cases = (
            (
                "cosmos3-nano-t2v.json",
                "cosmos3-nano-t2v.lock.json",
                "Cosmos3-Nano/transformer/diffusion_pytorch_model.safetensors",
                "Cosmos3-Nano-int4-convrot.safetensors",
                False,
            ),
            (
                "cosmos3-super-t2v.json",
                "cosmos3-super-t2v.lock.json",
                "Cosmos3-Super/transformer/diffusion_pytorch_model.safetensors",
                "Cosmos3-Super-int4-convrot.safetensors",
                True,
            ),
            (
                "cosmos3-super-text2image.json",
                "cosmos3-super-text2image.lock.json",
                "Cosmos3-Super/transformer/diffusion_pytorch_model.safetensors",
                "Cosmos3-Super-int4-convrot.safetensors",
                True,
            ),
            (
                "cosmos3-super-image2video.json",
                "cosmos3-super-image2video.lock.json",
                "Cosmos3-Super-Image2Video/transformer/diffusion_pytorch_model.safetensors",
                "Cosmos3-Super-Image2Video-int4-convrot.safetensors",
                True,
            ),
            (
                "cosmos3-edge-t2v.json",
                "cosmos3-edge-t2v.lock.json",
                "Cosmos3-Edge/transformer/diffusion_pytorch_model.safetensors",
                "Cosmos3-Edge-int4-convrot.safetensors",
                False,
            ),
            (
                "cosmos3-super-image2video-4step.json",
                "cosmos3-super-image2video-4step.lock.json",
                "Cosmos3-Super-Image2Video-4Step/transformer/diffusion_pytorch_model.safetensors",
                "Cosmos3-Super-Image2Video-4Step-int4-convrot.safetensors",
                True,
            ),
            (
                "cosmos3-super-text2image-4step.json",
                "cosmos3-super-text2image-4step.lock.json",
                "Cosmos3-Super-Image2Video-4Step/transformer/diffusion_pytorch_model.safetensors",
                "Cosmos3-Super-Image2Video-4Step-int4-convrot.safetensors",
                True,
            ),
        )
        self.assertIn("cosmos3", recipes.MODEL_DIRS)
        for workflow_name, lock_name, filename, convrot, split in cases:
            source = ROOT / "examples" / workflow_name
            lock_path = ROOT / "examples" / lock_name
            committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
            self.assertTrue(
                workflow_resolver.lock_matches_workflow(committed, source),
                workflow_name,
            )
            self.assertEqual(committed["unresolved"], [])
            self.assertEqual(len(committed["custom_nodes"]), 1, workflow_name)
            node = committed["custom_nodes"][0]
            self.assertEqual(node["id"], "ComfyUI-Cosmos3")
            self.assertEqual(node["version"], "main")
            self.assertEqual(
                node["url"],
                "https://github.com/RyukoMatoiFan/ComfyUI-Cosmos3.git",
            )
            names = {(m["category"], m["filename"]) for m in committed["models"]}
            self.assertIn(("cosmos3", filename), names, workflow_name)
            urls = {m["filename"]: m["url"] for m in committed["models"]}
            self.assertIn(convrot, urls[filename], workflow_name)
            text = source.read_text(encoding="utf-8")
            self.assertIn('"cnr_id": "ComfyUI-Cosmos3"', text)
            if split:
                self.assertIn("Cosmos3UndTowerLoader", text)
            if "4step" in workflow_name:
                self.assertIn("distilled_4step", text, workflow_name)
                self.assertIn('"euler"', text, workflow_name)
            reused, origin = workflow_resolver.select_workflow_lock(source, lock_path)
            self.assertEqual(origin, "reused", workflow_name)
            self.assertEqual(len(reused["models"]), len(committed["models"]))

    def test_ltx_lock_is_curated_and_matches_workflow_hash(self):
        source = ROOT / "examples" / "ltx-2.5-t2v-i2v-distilled.json"
        lock_path = ROOT / "examples" / "ltx-2.5-t2v-i2v-distilled.lock.json"
        committed = workflow_resolver.load_workflow_lock(lock_path, require_resolved=True)
        self.assertTrue(workflow_resolver.lock_matches_workflow(committed, source))
        self.assertEqual(committed["unresolved"], [])
        fresh = workflow_resolver.resolve_workflow(source)
        self.assertTrue(fresh["unresolved"])
        reused, origin = workflow_resolver.select_workflow_lock(source, lock_path)
        self.assertEqual(origin, "reused")
        self.assertEqual(len(reused["models"]), len(committed["models"]))


class RecipeUrlTests(unittest.TestCase):
    def test_download_urls_use_resolve_and_numeric_civitai_ids(self):
        for pack_name, categories in recipes.MODEL_PACKS.items():
            for category, assets in categories.items():
                for asset in assets:
                    url = asset.url
                    host = urlparse(url).netloc
                    if "huggingface.co" in host:
                        self.assertNotIn(
                            "/blob/",
                            url,
                            f"{pack_name}/{category} still uses /blob/: {url}",
                        )
                        self.assertIn("/resolve/", normalize_huggingface_url(url))
                    if "civitai.com" in host:
                        self.assertRegex(
                            url,
                            CIVITAI_ID,
                            f"{pack_name}/{category} has a non-numeric Civitai id: {url}",
                        )


class ScriptContractTests(unittest.TestCase):
    def test_z_image_script_uses_lock_filenames(self):
        lock = workflow_resolver.load_workflow_lock(
            ROOT / "examples" / "z-image-base.lock.json",
            require_resolved=True,
        )
        names = {model["filename"] for model in lock["models"]}
        module = _load_script("run_z_image_prompts.py")
        graph = module._prompt_graph("hello", seed=1)
        self.assertIn(graph["66"]["inputs"]["unet_name"], names)
        self.assertIn(graph["62"]["inputs"]["clip_name"], names)
        self.assertIn(graph["63"]["inputs"]["vae_name"], names)

    def test_ltx_example_still_has_nodes_the_compat_script_patches(self):
        text = (ROOT / "examples" / "ltx-2.5-t2v-i2v-distilled.json").read_text(
            encoding="utf-8"
        )
        self.assertIn("GemmaAPITextEncode", text)
        self.assertIn("LTXFloatToInt", text)
        self.assertIn("ltx-2.5-22b-distilled-transformer-bf16.safetensors", text)
        self.assertIn('"frontendVersion": "1.48.7"', text)


if __name__ == "__main__":
    unittest.main()
