import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import workflow_resolver
from catalog import (
    DEFAULT_CATALOG_ID,
    ROOT,
    apply_catalog_hydrate,
    bind_graph,
    build_prompt,
    catalog_hydrate_rows,
    list_catalogs,
    load_catalog,
    lock_path,
    public_catalog,
    validate_catalog,
    workflow_path,
)
from catalog.gates import (
    GRAPH_MODE_IDS,
    INFERENCE_GPU,
    NON_L40S_DEFAULT_GPU_IDS,
    TEST_GPU,
)


class CatalogInvariantTests(unittest.TestCase):
    def test_every_recipe_follows_the_gates(self):
        items = list_catalogs()
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(items[0]["id"], DEFAULT_CATALOG_ID)
        for item in items:
            catalog = load_catalog(item["id"])
            self.assertEqual(catalog["id"], item["id"])
            self.assertEqual(catalog["gpu_inference"], INFERENCE_GPU, item["id"])
            self.assertIn(catalog["gpu"], catalog["gpu_choices"], item["id"])
            self.assertIn(INFERENCE_GPU, catalog["gpu_choices"], item["id"])
            self.assertNotIn("T4", catalog["gpu_choices"], item["id"])
            self.assertTrue(workflow_path(catalog).is_file(), item["id"])
            self.assertTrue(lock_path(catalog).is_file(), item["id"])
            lock = workflow_resolver.load_workflow_lock(
                ROOT / catalog["lock"],
                require_resolved=True,
            )
            self.assertTrue(
                workflow_resolver.lock_matches_workflow(lock, ROOT / catalog["workflow"]),
                item["id"],
            )
            if item["id"] in GRAPH_MODE_IDS:
                self.assertEqual(catalog["mode"], "graph", item["id"])
                self.assertIsInstance(catalog.get("graph"), dict, item["id"])
            else:
                self.assertEqual(catalog["mode"], "workflow", item["id"])
                self.assertNotIn("graph", catalog)
            if item["id"] in NON_L40S_DEFAULT_GPU_IDS:
                self.assertNotEqual(catalog["gpu"], TEST_GPU, item["id"])
            else:
                self.assertEqual(catalog["gpu"], TEST_GPU, item["id"])
            for spec in catalog.get("params") or ():
                if spec.get("minimum") is not None and spec.get("maximum") is not None:
                    if spec["minimum"] == spec["maximum"]:
                        self.assertEqual(
                            spec.get("default"),
                            spec["minimum"],
                            f"{item['id']}.{spec.get('id')}",
                        )

    def test_hydrate_alias_uses_repo_relative_paths(self):
        workflow, lock = apply_catalog_hydrate("z-image")
        self.assertEqual(workflow, "examples/z-image-base.json")
        self.assertEqual(lock, "examples/z-image-base.lock.json")
        explicit_workflow, explicit_lock = apply_catalog_hydrate(
            "z-image",
            workflow="examples/other.json",
            lock_out="tmp/other.lock.json",
        )
        self.assertEqual(explicit_workflow, "examples/other.json")
        self.assertEqual(explicit_lock, "tmp/other.lock.json")
        rows = catalog_hydrate_rows()
        self.assertEqual(rows[0]["id"], DEFAULT_CATALOG_ID)
        self.assertEqual(
            [row["id"] for row in rows],
            [item["id"] for item in list_catalogs()],
        )
        for row in rows:
            self.assertTrue((ROOT / row["workflow"]).is_file(), row["id"])
            self.assertTrue((ROOT / row["lock"]).is_file(), row["id"])
        with self.assertRaises(FileNotFoundError):
            apply_catalog_hydrate("not-a-recipe")


class GraphExceptionTests(unittest.TestCase):
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
        self.assertFalse(public_catalog(catalog)["io"]["negative"])

    def test_rejects_unknown_placeholder(self):
        catalog = dict(load_catalog("z-image"))
        catalog["graph"] = {"1": {"class_type": "X", "inputs": {"text": "$missing"}}}
        with self.assertRaises(KeyError):
            bind_graph(catalog, {"prompt": "x", "seed": 1})


class WorkflowHappyPathTests(unittest.TestCase):
    def test_pixal3d_is_the_workflow_template(self):
        catalog = load_catalog("pixal3d")
        self.assertEqual(catalog["mode"], "workflow")
        self.assertNotIn("graph", catalog)
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


class CatalogGateTests(unittest.TestCase):
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

    def test_rejects_graph_mode_outside_allowlist(self):
        catalog = dict(load_catalog("pixal3d"))
        catalog["mode"] = "graph"
        catalog["graph"] = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "x.png"}}
        }
        with self.assertRaisesRegex(ValueError, "mode=graph is gated"):
            validate_catalog(catalog)

    def test_rejects_embedded_graph_on_workflow_mode(self):
        catalog = dict(load_catalog("pixal3d"))
        catalog["graph"] = {"1": {"class_type": "LoadImage", "inputs": {}}}
        with self.assertRaisesRegex(ValueError, "must not embed a graph"):
            validate_catalog(catalog)

    def test_rejects_pro6000_test_default_outside_allowlist(self):
        catalog = dict(load_catalog("pixal3d"))
        catalog["gpu"] = "RTX-PRO-6000"
        with self.assertRaisesRegex(ValueError, "NON_L40S_DEFAULT_GPU_IDS"):
            validate_catalog(catalog)

    def test_studio_html_has_recipe_and_upload_slots(self):
        html = Path(__file__).resolve().parents[1] / "studio" / "static" / "index.html"
        text = html.read_text(encoding="utf-8")
        self.assertIn('id="recipe"', text)
        self.assertIn('id="uploads"', text)


class CatalogJobPlanTests(unittest.TestCase):
    def test_prompt_recipes_split_on_prompts(self):
        from studio.server import iter_generate_jobs

        catalog = next(
            load_catalog(item["id"])
            for item in list_catalogs()
            if item["io"]["prompt"] and not item["io"]["images_in"]
        )
        with self.assertRaisesRegex(RuntimeError, "提示词"):
            iter_generate_jobs(catalog, {})
        jobs = iter_generate_jobs(catalog, {"prompts": "one\ntwo"})
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["prompt"], "one")
        self.assertIsNone(jobs[0]["image"])

    def test_image_recipes_split_on_uploads(self):
        from studio.server import iter_generate_jobs

        catalog = next(
            load_catalog(item["id"])
            for item in list_catalogs()
            if item["io"]["images_required"] and not item["io"]["prompt"]
        )
        with self.assertRaisesRegex(RuntimeError, "输入图"):
            iter_generate_jobs(catalog, {"prompts": []})
        jobs = iter_generate_jobs(catalog, {"images": ["a.png", "b.png"]})
        self.assertEqual([item["image"] for item in jobs], ["a.png", "b.png"])

    def test_image_and_prompt_recipes_need_both(self):
        from studio.server import iter_generate_jobs

        catalog = next(
            load_catalog(item["id"])
            for item in list_catalogs()
            if item["io"]["images_in"] and item["io"]["prompt"]
        )
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
