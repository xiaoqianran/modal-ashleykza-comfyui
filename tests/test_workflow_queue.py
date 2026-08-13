import json
import unittest
from pathlib import Path

import workflow_queue

ROOT = Path(__file__).resolve().parents[1]


class WorkflowInspectTests(unittest.TestCase):
    def test_detects_api_prompt(self):
        payload = {
            "12": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
            "13": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "hello"},
                "_meta": {"title": "Positive"},
            },
            "14": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": ""},
                "_meta": {"title": "Negative"},
            },
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "out"}},
        }
        self.assertTrue(workflow_queue.is_api_prompt(payload))
        self.assertFalse(workflow_queue.is_ui_workflow(payload))
        inspect = workflow_queue.inspect_workflow(payload)
        binds = {item["bind"] for item in inspect["nodes"]}
        self.assertEqual(inspect["format"], "api")
        self.assertIn("image", binds)
        self.assertIn("prompt", binds)
        self.assertIn("negative", binds)
        self.assertIn("save", binds)

    def test_detects_ui_workflow(self):
        payload = {
            "nodes": [
                {"id": 1, "type": "LoadImage", "title": "Load"},
                {"id": 2, "type": "SaveVideo", "title": "Save"},
            ]
        }
        self.assertTrue(workflow_queue.is_ui_workflow(payload))
        self.assertFalse(workflow_queue.is_api_prompt(payload))
        inspect = workflow_queue.inspect_workflow(payload)
        self.assertEqual(inspect["format"], "ui")
        self.assertEqual(inspect["nodes"][0]["bind"], "image")
        self.assertEqual(inspect["nodes"][1]["bind"], "save")

    def test_example_ui_json_is_inspectable_without_gpu(self):
        for name in (
            "z-image-base.json",
            "ltx-2.5-t2v-i2v-distilled.json",
            "triposplat-image-to-gaussian-splat.json",
            "pixal3d-image-to-3d.json",
        ):
            payload = json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))
            inspect = workflow_queue.inspect_workflow(payload)
            self.assertEqual(inspect["format"], "ui", name)
            self.assertTrue(inspect["nodes"], name)


class WorkflowBindTests(unittest.TestCase):
    def test_bind_load_image_and_text(self):
        prompt = {
            "12": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "13": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "old", "clip": ["1", 0]},
                "_meta": {"title": "Positive"},
            },
            "14": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "neg", "clip": ["1", 0]},
                "_meta": {"title": "Negative"},
            },
        }
        workflow_queue.bind_load_image(prompt, "chair.png")
        workflow_queue.bind_text_prompt(prompt, text="a teapot", negative="blur")
        self.assertEqual(prompt["12"]["inputs"]["image"], "chair.png")
        self.assertEqual(prompt["13"]["inputs"]["text"], "a teapot")
        self.assertEqual(prompt["14"]["inputs"]["text"], "blur")
        self.assertEqual(prompt["13"]["inputs"]["clip"], ["1", 0])

    def test_bind_number_inputs_only_touches_existing_keys(self):
        prompt = {
            "9": {
                "class_type": "KSampler",
                "inputs": {"seed": 1, "steps": 20, "cfg": 4.0, "model": ["1", 0]},
            },
            "8": {
                "class_type": "EmptySD3LatentImage",
                "inputs": {"width": 512, "height": 512, "batch_size": 1},
            },
        }
        workflow_queue.bind_number_inputs(
            prompt,
            {"seed": 99, "steps": 8, "width": 1024, "foo": 1},
        )
        self.assertEqual(prompt["9"]["inputs"]["seed"], 99)
        self.assertEqual(prompt["9"]["inputs"]["steps"], 8)
        self.assertEqual(prompt["9"]["inputs"]["cfg"], 4.0)
        self.assertEqual(prompt["8"]["inputs"]["width"], 1024)
        self.assertEqual(prompt["8"]["inputs"]["batch_size"], 1)

    def test_to_api_prompt_passthrough(self):
        payload = {"1": {"class_type": "SaveImage", "inputs": {}}}
        self.assertEqual(workflow_queue.to_api_prompt(None, payload), payload)

    def test_inspect_cli_does_not_need_base_url(self):
        import io
        from contextlib import redirect_stdout

        source = ROOT / "examples" / "z-image-base.json"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            workflow_queue.main(["--inspect", "--workflow", str(source)])
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["format"], "ui")
        self.assertTrue(payload["nodes"])


if __name__ == "__main__":
    unittest.main()
