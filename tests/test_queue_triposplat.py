import importlib.util
import unittest
from pathlib import Path


def _load_queue_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "queue_triposplat.py"
    spec = importlib.util.spec_from_file_location("queue_triposplat", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TripoSplatWorkflowPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_queue_module()

    def test_enable_glb_export_unbypasses_mesh_and_save_nodes(self):
        workflow = {
            "nodes": [
                {"id": 51, "type": "SaveGLB", "mode": 0},
                {"id": 76, "type": "SplatToMesh", "mode": 4},
                {"id": 67, "type": "SaveGLB", "mode": 4},
                {"id": 92, "type": "SplatToFile3D", "mode": 0},
            ]
        }
        patched = self.mod.enable_glb_export(workflow)
        by_id = {node["id"]: node for node in patched["nodes"]}
        self.assertEqual(by_id[51]["mode"], 0)
        self.assertEqual(by_id[76]["mode"], 0)
        self.assertEqual(by_id[67]["mode"], 0)
        self.assertEqual(by_id[92]["mode"], 0)

    def test_example_workflow_has_bypassed_mesh_export(self):
        import json

        source = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "triposplat-image-to-gaussian-splat.json"
        )
        workflow = json.loads(source.read_text(encoding="utf-8"))
        by_id = {node["id"]: node for node in workflow["nodes"]}
        self.assertEqual(by_id[76]["type"], "SplatToMesh")
        self.assertEqual(by_id[76]["mode"], 4)
        self.assertEqual(by_id[67]["type"], "SaveGLB")
        self.assertEqual(by_id[67]["mode"], 4)
        self.assertEqual(by_id[51]["mode"], 0)
        patched = self.mod.enable_glb_export(json.loads(json.dumps(workflow)))
        patched_by_id = {node["id"]: node for node in patched["nodes"]}
        self.assertEqual(patched_by_id[76]["mode"], 0)
        self.assertEqual(patched_by_id[67]["mode"], 0)

    def test_bind_load_image_sets_filename(self):
        prompt = {
            "12": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "13": {"class_type": "SaveGLB", "inputs": {}},
        }
        bound = self.mod.bind_load_image(prompt, "chair.png")
        self.assertEqual(bound["12"]["inputs"]["image"], "chair.png")
