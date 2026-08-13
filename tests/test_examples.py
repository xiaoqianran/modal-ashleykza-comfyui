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
        self.assertTrue(str(pixal.get("url", "")).startswith("https://github.com/Saganaki22/Pixal3D-ComfyUI"))
        names = {(m["category"], m["filename"]) for m in committed["models"]}
        self.assertIn(("Pixal3D", "TencentARC_Pixal3D/pipeline.json"), names)
        self.assertIn(("geometry_estimation", "moge_2_vitl_normal_fp16.safetensors"), names)
        self.assertIn("Pixal3D", recipes.MODEL_DIRS)
        self.assertIn("geometry_estimation", recipes.MODEL_DIRS)
        reused, origin = workflow_resolver.select_workflow_lock(source, lock_path)
        self.assertEqual(origin, "reused")
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
