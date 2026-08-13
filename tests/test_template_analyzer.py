import json
import tempfile
import unittest
from pathlib import Path

import recipes
import template_analyzer
import workflow_resolver

ROOT = Path(__file__).resolve().parents[1]


def _write_workflow(directory: Path, name: str, payload: dict) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class ModelPatchCategoryTests(unittest.TestCase):
    def test_model_patches_is_a_known_storage_dir(self):
        self.assertIn("model_patches", recipes.MODEL_DIRS)
        self.assertIn("audio_encoders", recipes.MODEL_DIRS)
        self.assertIn("detection", recipes.MODEL_DIRS)
        self.assertIn("frame_interpolation", recipes.MODEL_DIRS)
        self.assertIn("optical_flow", recipes.MODEL_DIRS)


class ClassifySyntheticTests(unittest.TestCase):
    def test_api_prefix_is_cloud(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = _write_workflow(
                root,
                "api_openai_chat.json",
                {
                    "nodes": [
                        {
                            "id": 1,
                            "type": "OpenAIChat",
                            "properties": {"cnr_id": "comfy-core"},
                            "widgets_values": [],
                        }
                    ]
                },
            )
            record = template_analyzer.classify_workflow(path)
            self.assertTrue(record["api"])
            self.assertEqual(record["bucket"], "api_cloud")

    def test_hydrate_ready_core_checkpoint(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = _write_workflow(
                root,
                "sdxl_simple_example.json",
                {
                    "nodes": [
                        {
                            "id": 4,
                            "type": "CheckpointLoaderSimple",
                            "properties": {"cnr_id": "comfy-core", "ver": "0.3.33"},
                            "widgets_values": ["sd_xl_base_1.0.safetensors"],
                        }
                    ],
                    "models": [
                        {
                            "name": "sd_xl_base_1.0.safetensors",
                            "directory": "checkpoints",
                            "url": "https://huggingface.co/example/sd_xl_base_1.0.safetensors",
                        }
                    ],
                },
            )
            record = template_analyzer.classify_workflow(path)
            self.assertEqual(record["bucket"], "hydrate_ready")
            self.assertEqual(record["n_models"], 1)
            self.assertEqual(record["n_custom"], 0)

    def test_needs_cnr(self):
        with tempfile.TemporaryDirectory() as raw:
            path = _write_workflow(
                Path(raw),
                "template_essentials.json",
                {
                    "nodes": [
                        {
                            "id": 2,
                            "type": "ImageResize+",
                            "properties": {"cnr_id": "comfyui_essentials", "ver": "1.1.0"},
                            "widgets_values": [],
                        }
                    ]
                },
            )
            record = template_analyzer.classify_workflow(path)
            self.assertEqual(record["bucket"], "needs_cnr")
            self.assertIn("comfyui_essentials", record["custom_ids"])

    def test_scan_buckets_and_json_report(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_workflow(
                root,
                "api_foo.json",
                {"nodes": [{"id": 1, "type": "Note", "properties": {}, "widgets_values": []}]},
            )
            _write_workflow(
                root,
                "utility_blank.json",
                {"nodes": [{"id": 1, "type": "Note", "properties": {"cnr_id": "comfy-core"}}]},
            )
            report = template_analyzer.scan_templates(root)
            self.assertEqual(report["count"], 2)
            self.assertEqual(report["buckets"]["api_cloud"], 1)
            dumped = json.dumps(report)
            self.assertIn("utility_blank.json", dumped)


class RealTemplateSmokeTests(unittest.TestCase):
    def test_sdxl_simple_fixture_is_hydrate_ready(self):
        source = ROOT / "tests" / "fixtures" / "comfy_templates" / "sdxl_simple_example.json"
        if not source.is_file():
            self.skipTest("fixture not vendored")
        lock = workflow_resolver.resolve_workflow(source)
        self.assertEqual(lock["unresolved"], [])
        self.assertTrue(lock["models"])
        record = template_analyzer.classify_workflow(source)
        self.assertEqual(record["bucket"], "hydrate_ready")
        self.assertEqual(record["format"], "ui")


if __name__ == "__main__":
    unittest.main()
