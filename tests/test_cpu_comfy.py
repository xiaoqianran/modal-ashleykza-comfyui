import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cpu_comfy import missing_model_files, missing_node_types, probe_running, workflow_class_types


class CpuComfyProbeTests(unittest.TestCase):
    def test_workflow_class_types_skips_notes_and_duplicates(self):
        workflow = {
            "nodes": [
                {"id": 1, "type": "LoadImage"},
                {"id": 2, "type": "LoadImage"},
                {"id": 3, "type": "Note"},
                {"id": 4, "type": "Trellis2LoadModel"},
                {"id": 5, "type": "PrimitiveFloat"},
            ]
        }
        self.assertEqual(
            workflow_class_types(workflow),
            ["LoadImage", "Trellis2LoadModel"],
        )

    def test_missing_node_types_and_model_files(self):
        required = ["LoadImage", "Trellis2LoadModel"]
        self.assertEqual(
            missing_node_types(required, {"LoadImage": {}}),
            ["Trellis2LoadModel"],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "loras").mkdir()
            (root / "loras" / "have.safetensors").write_bytes(b"x")
            missing = missing_model_files(
                [
                    {"category": "loras", "filename": "have.safetensors"},
                    {"category": "loras", "filename": "need.safetensors"},
                ],
                root,
            )
        self.assertEqual(missing[0]["filename"], "need.safetensors")

    def test_probe_running_reads_object_info(self):
        workflow = {"nodes": [{"id": 1, "type": "KJNode"}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "cpu_comfy.http_json",
                return_value={"LoadImage": {}},
            ):
                report = probe_running(
                    "http://127.0.0.1:8188",
                    workflow,
                    models=[{"category": "loras", "filename": "x.safetensors"}],
                    storage_root=root,
                )
        self.assertEqual(report["missing_nodes"], ["KJNode"])
        self.assertEqual(report["missing_models"][0]["filename"], "x.safetensors")


if __name__ == "__main__":
    unittest.main()
