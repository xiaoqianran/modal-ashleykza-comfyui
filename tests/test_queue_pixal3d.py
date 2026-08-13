import importlib.util
import unittest
from pathlib import Path


def _load_queue_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "queue_pixal3d.py"
    spec = importlib.util.spec_from_file_location("queue_pixal3d", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Pixal3DQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_queue_module()

    def test_bind_load_image_sets_filename(self):
        prompt = {
            "15": {"class_type": "LoadImage", "inputs": {"image": "gecko.png"}},
            "17": {"class_type": "Pixal3DExportGLB", "inputs": {}},
        }
        bound = self.mod.bind_load_image(prompt, "chair.png")
        self.assertEqual(bound["15"]["inputs"]["image"], "chair.png")

    def test_iter_glb_names_finds_export_path(self):
        history = {
            "outputs": {
                "17": {"text": [r"C:\Users\me\output\pixal3d_demo.glb"]}
            }
        }
        names = self.mod._iter_glb_names(history)
        self.assertEqual(names, ["C:/Users/me/output/pixal3d_demo.glb"])
