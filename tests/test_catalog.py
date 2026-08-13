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
        self.assertEqual(items[0]["kind"], "t2i")
        self.assertEqual(items[0]["io"]["images_in"], 0)

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
        self.assertEqual(catalog["gpu"], "T4")
        self.assertEqual(catalog["gpu_choices"][0], "T4")
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
        self.assertNotIn("T4", catalog["gpu_choices"])
        self.assertEqual(catalog["io"]["images_required"], 1)
        public = public_catalog(catalog)
        self.assertFalse(public["has_graph"])
        self.assertTrue(any(spec["type"] == "image" for spec in public["params"]))

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
        self.assertEqual(flux["mode"], "workflow")
        self.assertEqual(qwen["mode"], "workflow")
        self.assertNotIn("graph", flux)
        self.assertNotIn("graph", qwen)
        self.assertEqual(flux["gpu"], "RTX-PRO-6000")
        self.assertEqual(flux["gpu_choices"], ["RTX-PRO-6000"])
        self.assertEqual(qwen["gpu"], "RTX-PRO-6000")
        self.assertIn("RTX-PRO-6000", qwen["gpu_choices"])
        self.assertNotIn("T4", flux["gpu_choices"])
        self.assertTrue(public_catalog(flux)["io"]["prompt"])
        self.assertTrue(public_catalog(qwen)["io"]["prompt"])
        self.assertTrue(public_catalog(qwen)["io"]["negative"])
        self.assertFalse(public_catalog(flux)["io"]["negative"])

    def test_rejects_path_escape_in_workflow_field(self):
        catalog = dict(load_catalog("z-image"))
        catalog["workflow"] = "../.env"
        with self.assertRaises(ValueError):
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
