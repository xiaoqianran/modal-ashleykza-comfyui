import unittest
from pathlib import Path

import workflow_resolver
from catalog import ROOT, bind_graph, list_catalogs, load_catalog, workflow_path


class CatalogTests(unittest.TestCase):
    def test_lists_z_image(self):
        ids = {item["id"] for item in list_catalogs()}
        self.assertIn("z-image", ids)

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
        self.assertIsInstance(graph["68"]["inputs"]["width"], int)

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
        self.assertTrue((Path(__file__).resolve().parents[1] / "studio" / "static" / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
