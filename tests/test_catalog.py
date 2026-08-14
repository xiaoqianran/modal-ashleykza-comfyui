import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import workflow_resolver
from catalog import (
    DEFAULT_CATALOG_ID,
    ROOT,
    bind_graph,
    build_prompt,
    list_catalogs,
    load_catalog,
    public_catalog,
    validate_catalog,
    workflow_path,
)


class CatalogTests(unittest.TestCase):
    def test_lists_z_image_first(self):
        items = list_catalogs()
        ids = [item["id"] for item in items]
        self.assertEqual(ids[0], DEFAULT_CATALOG_ID)
        self.assertIn("pixal3d", ids)
        self.assertIn("triposplat", ids)
        self.assertIn("flux2-dev", ids)
        self.assertIn("qwen-image-2512", ids)
        self.assertIn("krea2-turbo", ids)
        self.assertIn("z-image-turbo", ids)
        self.assertIn("ideogram4", ids)
        self.assertIn("qwen-image-2512-lightning", ids)
        self.assertIn("cosmos3-nano", ids)
        self.assertIn("cosmos3-super", ids)
        self.assertIn("cosmos3-super-text2image", ids)
        self.assertIn("cosmos3-super-image2video", ids)
        self.assertIn("cosmos3-edge", ids)
        self.assertIn("cosmos3-super-image2video-4step", ids)
        self.assertIn("cosmos3-super-text2image-4step", ids)
        self.assertIn("hunyuan3d-2.1", ids)
        self.assertIn("trellis2", ids)
        self.assertEqual(items[0]["kind"], "t2i")
        self.assertEqual(items[0]["io"]["images_in"], 0)
        for item in items:
            self.assertEqual(item["gpu_inference"], "RTX-PRO-6000", item["id"])
            self.assertIn(item["gpu"], item["gpu_choices"], item["id"])
            self.assertIn("RTX-PRO-6000", item["gpu_choices"], item["id"])
            self.assertNotIn("T4", item["gpu_choices"], item["id"])
            if item["id"] not in {"flux2-dev", "trellis2"}:
                self.assertEqual(item["gpu"], "L40S", item["id"])

    def test_bind_graph_fills_prompt_and_seed(self):
        catalog = load_catalog("z-image")
        graph, values = bind_graph(
            catalog,
            {"prompt": "a celadon teapot", "seed": 42, "steps": 20},
        )
        self.assertEqual(graph["67"]["inputs"]["text"], "a celadon teapot")
        self.assertEqual(graph["69"]["inputs"]["seed"], 42)
        self.assertEqual(graph["69"]["inputs"]["steps"], 20)
        self.assertEqual(values["width"], 1024)
        self.assertEqual(catalog["gpu"], "L40S")
        self.assertEqual(catalog["gpu_inference"], "RTX-PRO-6000")
        self.assertEqual(catalog["gpu_choices"][0], "L40S")
        self.assertEqual(catalog["mode"], "graph")
        self.assertIsInstance(graph["68"]["inputs"]["width"], int)

    def test_public_catalog_hides_the_api_graph(self):
        public = public_catalog(load_catalog("z-image"))
        self.assertNotIn("graph", public)
        self.assertTrue(public["has_graph"])
        self.assertEqual(public["mode"], "graph")
        self.assertTrue(public["io"]["prompt"])

    def test_filenames_match_lock(self):
        catalog = load_catalog("z-image")
        lock = workflow_resolver.load_workflow_lock(
            ROOT / catalog["lock"],
            require_resolved=True,
        )
        names = {model["filename"] for model in lock["models"]}
        graph, _values = bind_graph(catalog, {"prompt": "hello", "seed": 1})
        self.assertIn(graph["66"]["inputs"]["unet_name"], names)
        self.assertIn(graph["62"]["inputs"]["clip_name"], names)
        self.assertIn(graph["63"]["inputs"]["vae_name"], names)

    def test_z_image_turbo_graph_uses_turbo_unet_and_eight_steps(self):
        catalog = load_catalog("z-image-turbo")
        lock = workflow_resolver.load_workflow_lock(
            ROOT / catalog["lock"],
            require_resolved=True,
        )
        names = {model["filename"] for model in lock["models"]}
        graph, values = bind_graph(catalog, {"prompt": "a harbor close-up", "seed": 7})
        self.assertEqual(graph["66"]["inputs"]["unet_name"], "z_image_turbo_bf16.safetensors")
        self.assertIn(graph["66"]["inputs"]["unet_name"], names)
        self.assertEqual(graph["69"]["inputs"]["cfg"], 1)
        self.assertEqual(graph["69"]["inputs"]["steps"], 8)
        self.assertEqual(graph["69"]["class_type"], "KSampler")
        self.assertEqual(graph["71"]["class_type"], "ConditioningZeroOut")
        self.assertEqual(values["steps"], 8)
        self.assertEqual(catalog["gpu"], "L40S")
        self.assertFalse(public_catalog(catalog)["io"]["negative"])

    def test_rejects_unknown_placeholder(self):
        catalog = dict(load_catalog("z-image"))
        catalog["graph"] = {"1": {"class_type": "X", "inputs": {"text": "$missing"}}}
        with self.assertRaises(KeyError):
            bind_graph(catalog, {"prompt": "x", "seed": 1})

    def test_workflow_file_exists(self):
        self.assertTrue(workflow_path(load_catalog("z-image")).is_file())
        html = Path(__file__).resolve().parents[1] / "studio" / "static" / "index.html"
        self.assertTrue(html.is_file())
        text = html.read_text(encoding="utf-8")
        self.assertIn('id="recipe"', text)
        self.assertIn('id="uploads"', text)

    def test_pixal3d_is_workflow_mode_with_image_slot(self):
        catalog = load_catalog("pixal3d")
        self.assertEqual(catalog["mode"], "workflow")
        self.assertNotIn("graph", catalog)
        self.assertEqual(catalog["gpu"], "L40S")
        self.assertEqual(catalog["gpu_inference"], "RTX-PRO-6000")
        self.assertNotIn("T4", catalog["gpu_choices"])
        self.assertEqual(catalog["io"]["images_required"], 1)
        public = public_catalog(catalog)
        self.assertFalse(public["has_graph"])
        self.assertTrue(any(spec["type"] == "image" for spec in public["params"]))

    def test_hunyuan3d_and_trellis2_are_workflow_mode_with_image_slot(self):
        hunyuan = load_catalog("hunyuan3d-2.1")
        trellis = load_catalog("trellis2")
        for catalog in (hunyuan, trellis):
            self.assertEqual(catalog["mode"], "workflow", catalog["id"])
            self.assertNotIn("graph", catalog)
            self.assertEqual(catalog["gpu_inference"], "RTX-PRO-6000", catalog["id"])
            self.assertNotIn("T4", catalog["gpu_choices"])
            self.assertEqual(catalog["kind"], "i23d", catalog["id"])
            self.assertEqual(catalog["io"]["images_required"], 1, catalog["id"])
            public = public_catalog(catalog)
            self.assertFalse(public["has_graph"], catalog["id"])
            self.assertTrue(any(spec["type"] == "image" for spec in public["params"]), catalog["id"])
        self.assertEqual(hunyuan["gpu"], "L40S")
        self.assertEqual(trellis["gpu"], "RTX-PRO-6000")
        self.assertEqual(trellis["gpu_choices"], ["RTX-PRO-6000"])

    def test_workflow_mode_binds_loadimage_without_embedded_graph(self):
        api_prompt = {
            "12": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "13": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "old"},
                "_meta": {"title": "Positive"},
            },
        }
        graph, _values = build_prompt(
            load_catalog("pixal3d"),
            {},
            api_prompt=api_prompt,
            image_name="chair.png",
        )
        self.assertEqual(graph["12"]["inputs"]["image"], "chair.png")
        self.assertEqual(api_prompt["12"]["inputs"]["image"], "old.png")

    def test_flux2_and_qwen2512_are_workflow_mode_on_pro6000(self):
        flux = load_catalog("flux2-dev")
        qwen = load_catalog("qwen-image-2512")
        krea = load_catalog("krea2-turbo")
        turbo = load_catalog("z-image-turbo")
        ideogram = load_catalog("ideogram4")
        self.assertEqual(flux["mode"], "workflow")
        self.assertEqual(qwen["mode"], "workflow")
        self.assertEqual(krea["mode"], "workflow")
        self.assertEqual(ideogram["mode"], "workflow")
        self.assertEqual(turbo["mode"], "graph")
        self.assertNotIn("graph", flux)
        self.assertNotIn("graph", qwen)
        self.assertNotIn("graph", krea)
        self.assertNotIn("graph", ideogram)
        self.assertIn("graph", turbo)
        self.assertEqual(flux["gpu"], "RTX-PRO-6000")
        self.assertEqual(flux["gpu_inference"], "RTX-PRO-6000")
        self.assertEqual(flux["gpu_choices"], ["RTX-PRO-6000"])
        self.assertEqual(load_catalog("trellis2")["gpu"], "RTX-PRO-6000")
        self.assertEqual(load_catalog("trellis2")["gpu_choices"], ["RTX-PRO-6000"])
        self.assertEqual(qwen["gpu"], "L40S")
        self.assertEqual(qwen["gpu_inference"], "RTX-PRO-6000")
        self.assertEqual(qwen["gpu_choices"], ["L40S", "RTX-PRO-6000"])
        self.assertEqual(krea["gpu"], "L40S")
        self.assertEqual(krea["gpu_inference"], "RTX-PRO-6000")
        self.assertEqual(krea["gpu_choices"], ["L40S", "RTX-PRO-6000"])
        self.assertEqual(turbo["gpu"], "L40S")
        self.assertEqual(turbo["gpu_inference"], "RTX-PRO-6000")
        self.assertEqual(turbo["gpu_choices"], ["L40S", "RTX-PRO-6000"])
        self.assertEqual(ideogram["gpu"], "L40S")
        self.assertEqual(ideogram["gpu_inference"], "RTX-PRO-6000")
        self.assertEqual(ideogram["gpu_choices"], ["L40S", "RTX-PRO-6000"])
        self.assertNotIn("T4", flux["gpu_choices"])
        self.assertNotIn("T4", qwen["gpu_choices"])
        self.assertNotIn("T4", krea["gpu_choices"])
        self.assertNotIn("T4", turbo["gpu_choices"])
        self.assertNotIn("T4", ideogram["gpu_choices"])
        self.assertTrue(public_catalog(flux)["io"]["prompt"])
        self.assertTrue(public_catalog(qwen)["io"]["prompt"])
        self.assertTrue(public_catalog(krea)["io"]["prompt"])
        self.assertTrue(public_catalog(turbo)["io"]["prompt"])
        self.assertTrue(public_catalog(ideogram)["io"]["prompt"])
        self.assertTrue(public_catalog(qwen)["io"]["negative"])
        self.assertFalse(public_catalog(flux)["io"]["negative"])
        self.assertFalse(public_catalog(krea)["io"]["negative"])
        self.assertFalse(public_catalog(turbo)["io"]["negative"])
        self.assertFalse(public_catalog(ideogram)["io"]["negative"])

    def test_qwen_image_2512_lightning_is_eight_step_workflow(self):
        catalog = load_catalog("qwen-image-2512-lightning")
        lock = workflow_resolver.load_workflow_lock(
            ROOT / catalog["lock"],
            require_resolved=True,
        )
        names = {model["filename"] for model in lock["models"]}
        self.assertEqual(catalog["mode"], "workflow")
        self.assertNotIn("graph", catalog)
        self.assertEqual(catalog["gpu"], "L40S")
        self.assertEqual(catalog["gpu_inference"], "RTX-PRO-6000")
        self.assertNotIn("T4", catalog["gpu_choices"])
        self.assertEqual(
            next(spec["default"] for spec in catalog["params"] if spec["id"] == "steps"),
            8,
        )
        self.assertIn("Qwen-Image-2512-Lightning-8steps-V1.0-fp32.safetensors", names)
        self.assertIn("qwen_image_2512_fp8_e4m3fn.safetensors", names)
        public = public_catalog(catalog)
        self.assertTrue(public["io"]["prompt"])
        self.assertFalse(public["io"]["negative"])

    def test_cosmos3_recipes_are_workflow_mode_on_l40s(self):
        nano = load_catalog("cosmos3-nano")
        super_omni = load_catalog("cosmos3-super")
        t2i = load_catalog("cosmos3-super-text2image")
        i2v = load_catalog("cosmos3-super-image2video")
        edge = load_catalog("cosmos3-edge")
        i2v4 = load_catalog("cosmos3-super-image2video-4step")
        t2i4 = load_catalog("cosmos3-super-text2image-4step")
        self.assertEqual(nano["kind"], "t2v")
        self.assertEqual(super_omni["kind"], "t2v")
        self.assertEqual(t2i["kind"], "t2i")
        self.assertEqual(i2v["kind"], "i2v")
        self.assertEqual(edge["kind"], "t2v")
        self.assertEqual(i2v4["kind"], "i2v")
        self.assertEqual(t2i4["kind"], "t2i")
        self.assertEqual(i2v["io"]["images_in"], 1)
        self.assertEqual(i2v4["io"]["images_in"], 1)
        self.assertEqual(nano["io"]["images_in"], 0)
        self.assertEqual(edge["io"]["images_in"], 0)
        self.assertEqual(t2i4["io"]["images_in"], 0)
        for catalog in (nano, super_omni, t2i, i2v, edge, i2v4, t2i4):
            self.assertEqual(catalog["mode"], "workflow", catalog["id"])
            self.assertNotIn("graph", catalog)
            self.assertEqual(catalog["gpu"], "L40S", catalog["id"])
            self.assertEqual(catalog["gpu_inference"], "RTX-PRO-6000", catalog["id"])
            self.assertEqual(catalog["gpu_choices"], ["L40S", "RTX-PRO-6000"], catalog["id"])
            self.assertNotIn("T4", catalog["gpu_choices"])
            public = public_catalog(catalog)
            self.assertTrue(public["io"]["prompt"], catalog["id"])
            self.assertFalse(public["io"]["negative"], catalog["id"])
        lock = workflow_resolver.load_workflow_lock(ROOT / nano["lock"], require_resolved=True)
        names = {model["filename"] for model in lock["models"]}
        self.assertIn("Cosmos3-Nano/transformer/diffusion_pytorch_model.safetensors", names)
        t2i_lock = workflow_resolver.load_workflow_lock(ROOT / t2i["lock"], require_resolved=True)
        super_lock = workflow_resolver.load_workflow_lock(
            ROOT / super_omni["lock"], require_resolved=True
        )
        self.assertEqual(
            {(m["category"], m["filename"]) for m in t2i_lock["models"]},
            {(m["category"], m["filename"]) for m in super_lock["models"]},
        )
        i2v4_lock = workflow_resolver.load_workflow_lock(ROOT / i2v4["lock"], require_resolved=True)
        t2i4_lock = workflow_resolver.load_workflow_lock(ROOT / t2i4["lock"], require_resolved=True)
        self.assertEqual(
            {(m["category"], m["filename"]) for m in t2i4_lock["models"]},
            {(m["category"], m["filename"]) for m in i2v4_lock["models"]},
        )
        self.assertEqual(i2v4["params"][3]["default"], 4)
        self.assertEqual(t2i4["params"][2]["default"], 4)
        self.assertEqual(i2v4["params"][3]["minimum"], 4)
        self.assertEqual(i2v4["params"][3]["maximum"], 4)
        self.assertEqual(t2i4["params"][2]["minimum"], 4)
        self.assertEqual(t2i4["params"][2]["maximum"], 4)
        self.assertEqual(i2v4["params"][4]["default"], 1.0)
        self.assertEqual(t2i4["params"][3]["default"], 1.0)
        self.assertEqual(i2v4["params"][4]["minimum"], 1.0)
        self.assertEqual(i2v4["params"][4]["maximum"], 1.0)
        self.assertEqual(t2i4["params"][3]["minimum"], 1.0)
        self.assertEqual(t2i4["params"][3]["maximum"], 1.0)

    def test_rejects_path_escape_in_workflow_field(self):
        catalog = dict(load_catalog("z-image"))
        catalog["workflow"] = "../.env"
        with self.assertRaises(ValueError):
            validate_catalog(catalog)

    def test_rejects_gpu_inference_outside_choices(self):
        catalog = dict(load_catalog("z-image"))
        catalog["gpu_inference"] = "T4"
        with self.assertRaisesRegex(ValueError, "gpu_inference"):
            validate_catalog(catalog)


class CatalogJobPlanTests(unittest.TestCase):
    def test_z_image_needs_prompts(self):
        from studio.server import iter_generate_jobs

        catalog = load_catalog("z-image")
        with self.assertRaisesRegex(RuntimeError, "提示词"):
            iter_generate_jobs(catalog, {})
        jobs = iter_generate_jobs(catalog, {"prompts": "one\ntwo"})
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["prompt"], "one")
        self.assertIsNone(jobs[0]["image"])

    def test_pixal3d_needs_images_and_splits_jobs(self):
        from studio.server import iter_generate_jobs

        catalog = load_catalog("pixal3d")
        with self.assertRaisesRegex(RuntimeError, "输入图"):
            iter_generate_jobs(catalog, {"prompts": []})
        jobs = iter_generate_jobs(catalog, {"images": ["a.png", "b.png"]})
        self.assertEqual([item["image"] for item in jobs], ["a.png", "b.png"])

    def test_hunyuan3d_and_trellis2_need_images_and_split_jobs(self):
        from studio.server import iter_generate_jobs

        for recipe_id in ("hunyuan3d-2.1", "trellis2"):
            catalog = load_catalog(recipe_id)
            with self.assertRaisesRegex(RuntimeError, "输入图"):
                iter_generate_jobs(catalog, {"prompts": []})
            jobs = iter_generate_jobs(catalog, {"images": ["a.png", "b.png"]})
            self.assertEqual([item["image"] for item in jobs], ["a.png", "b.png"], recipe_id)

    def test_cosmos3_i2v_needs_image_and_prompt(self):
        from studio.server import iter_generate_jobs

        catalog = load_catalog("cosmos3-super-image2video")
        with self.assertRaisesRegex(RuntimeError, "输入图"):
            iter_generate_jobs(catalog, {"prompts": ["move"]})
        with self.assertRaisesRegex(RuntimeError, "提示词"):
            iter_generate_jobs(catalog, {"images": ["a.png"]})
        jobs = iter_generate_jobs(
            catalog,
            {"prompts": ["move"], "images": ["a.png", "b.png"]},
        )
        self.assertEqual([item["image"] for item in jobs], ["a.png", "b.png"])
        self.assertEqual(jobs[0]["prompt"], "move")

    def test_cosmos3_i2v_4step_needs_image_and_prompt(self):
        from studio.server import iter_generate_jobs

        catalog = load_catalog("cosmos3-super-image2video-4step")
        with self.assertRaisesRegex(RuntimeError, "输入图"):
            iter_generate_jobs(catalog, {"prompts": ["move"]})
        jobs = iter_generate_jobs(
            catalog,
            {"prompts": ["move"], "images": ["a.png"]},
        )
        self.assertEqual(jobs[0]["image"], "a.png")
        self.assertEqual(jobs[0]["prompt"], "move")


class UploadTests(unittest.TestCase):
    def test_saves_png_and_rejects_unsafe_names(self):
        from studio import server

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(server, "UPLOAD_DIR", Path(directory)):
                path = server.save_upload("shot.png", b"\x89PNG")
                self.assertEqual(path.name, "shot.png")
                self.assertEqual(path.read_bytes(), b"\x89PNG")
                with self.assertRaises(ValueError):
                    server.save_upload("evil.exe", b"MZ")


if __name__ == "__main__":
    unittest.main()
