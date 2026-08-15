import importlib
import unittest

import sparse_3d_runtime
import workflow_queue
from catalog import ROOT, list_catalogs, load_catalog, validate_catalog
from catalog.gates import (
    ALLOWED_QUEUE_SCRIPTS,
    BINDER_CLASS_SETS,
    CUDA_VOLUME_GATE,
    GRAPH_MODE_IDS,
    OUT_OF_CATALOG_WORKFLOWS,
    extra_queue_scripts,
    queue_scripts,
)


class RecipeGateSurfaceTests(unittest.TestCase):
    def test_queue_scripts_stay_on_the_allowlist(self):
        found = queue_scripts(ROOT / "scripts")
        self.assertEqual(found, set(ALLOWED_QUEUE_SCRIPTS))
        self.assertFalse(extra_queue_scripts(ROOT / "scripts"))

    def test_ltx_workflow_is_not_a_catalog_recipe(self):
        workflows = {load_catalog(item["id"])["workflow"] for item in list_catalogs()}
        for path in OUT_OF_CATALOG_WORKFLOWS:
            self.assertTrue((ROOT / path).is_file(), path)
            self.assertNotIn(path, workflows)

    def test_graph_allowlist_matches_loaded_catalogs(self):
        graph_ids = {item["id"] for item in list_catalogs() if item["mode"] == "graph"}
        self.assertEqual(graph_ids, set(GRAPH_MODE_IDS))

    def test_binder_class_sets_exist(self):
        for dotted in BINDER_CLASS_SETS:
            module_name, attr = dotted.rsplit(".", 1)
            module = workflow_queue if module_name == "workflow_queue" else importlib.import_module(
                module_name
            )
            value = getattr(module, attr)
            self.assertTrue(value, dotted)

    def test_cuda_volume_gate_is_lock_based(self):
        module_name, attr = CUDA_VOLUME_GATE.rsplit(".", 1)
        self.assertEqual(module_name, "sparse_3d_runtime")
        fn = getattr(sparse_3d_runtime, attr)
        self.assertFalse(fn([]))
        self.assertTrue(fn([{"id": "Pixal3D-ComfyUI"}]))

    def test_comfy_env_volume_gate_is_lock_based(self):
        import sam3d_runtime
        from catalog.gates import COMFY_ENV_VOLUME_GATE

        module_name, attr = COMFY_ENV_VOLUME_GATE.rsplit(".", 1)
        self.assertEqual(module_name, "sam3d_runtime")
        fn = getattr(sam3d_runtime, attr)
        self.assertFalse(fn([]))
        self.assertFalse(fn([{"id": "ComfyUI-Trellis2"}]))
        self.assertTrue(fn([{"id": "ComfyUI-SAM3DObjects"}]))

    def test_ltx_path_cannot_enter_catalog(self):
        catalog = dict(load_catalog("pixal3d"))
        catalog["id"] = "ltx-25"
        catalog["workflow"] = next(iter(OUT_OF_CATALOG_WORKFLOWS))
        with self.assertRaisesRegex(ValueError, "stays out of catalog"):
            validate_catalog(catalog)
