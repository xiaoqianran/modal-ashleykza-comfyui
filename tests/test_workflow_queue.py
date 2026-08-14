import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            "hunyuan3d-2.1-image-to-3d.json",
            "trellis2-image-to-3d.json",
            "flux2-dev-t2i.json",
            "qwen-image-2512.json",
            "qwen-image-2512-lightning.json",
            "krea2-turbo-t2i.json",
            "z-image-turbo-t2i.json",
            "ideogram4-t2i.json",
            "cosmos3-nano-t2v.json",
            "cosmos3-super-t2v.json",
            "cosmos3-super-text2image.json",
            "cosmos3-super-image2video.json",
            "cosmos3-edge-t2v.json",
            "cosmos3-super-image2video-4step.json",
            "cosmos3-super-text2image-4step.json",
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

    def test_bind_text_prefers_user_prompt_widget_over_linked_clip(self):
        prompt = {
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": ["19", 0], "clip": ["1", 0]},
                "_meta": {"title": "CLIP Text Encode (Prompt)"},
            },
            "19": {
                "class_type": "PrimitiveStringMultiline",
                "inputs": {"value": "old"},
                "_meta": {"title": "Text String (User Prompt)"},
            },
        }
        workflow_queue.bind_text_prompt(prompt, text="a celadon teapot")
        self.assertEqual(prompt["19"]["inputs"]["value"], "a celadon teapot")
        self.assertEqual(prompt["6"]["inputs"]["text"], ["19", 0])

    def test_graph_to_prompt_waits_for_loaded_node_types(self):
        self.assertIn("expectedTypes.every", workflow_queue.GRAPH_TO_PROMPT_JS)
        self.assertIn("loaded_types", workflow_queue.GRAPH_TO_PROMPT_JS)
        self.assertIn("registered_node_types", workflow_queue.GRAPH_TO_PROMPT_JS)
        self.assertIn("nodeData", workflow_queue.GRAPH_TO_PROMPT_JS)
        self.assertIn("defined_types", workflow_queue.GRAPH_TO_PROMPT_JS)
        self.assertIn("entry.class_type = type", workflow_queue.GRAPH_TO_PROMPT_JS)

    def test_repair_converted_prompt_fills_class_type_and_unknown_widgets(self):
        prompt = {
            "2": {
                "class_type": None,
                "inputs": {
                    "UNKNOWN": "old prompt",
                    "UNKNOWN_1": 832,
                    "UNKNOWN_2": 480,
                    "text_encoder": ["1", 1],
                },
                "_meta": {"title": None},
            },
            "4": {
                "class_type": None,
                "inputs": {
                    "UNKNOWN": "",
                    "UNKNOWN_1": 832,
                    "UNKNOWN_2": 480,
                    "text_encoder": ["1", 1],
                    "prompt": ["3", 0],
                },
                "_meta": {"title": "Negative Prompt"},
            },
        }
        ui = {
            "nodes": [
                {"id": 2, "type": "Cosmos3TextEncode", "title": "Positive Prompt"},
                {"id": 4, "type": "Cosmos3TextEncode", "title": "Negative Prompt"},
            ]
        }
        info = {
            "Cosmos3TextEncode": {
                "input": {
                    "required": {
                        "text_encoder": ["COSMOS3_TEXT_ENCODER"],
                        "prompt": ["STRING", {}],
                        "width": ["INT", {}],
                        "height": ["INT", {}],
                    }
                }
            }
        }
        repaired = workflow_queue.repair_converted_prompt(prompt, ui, info)
        self.assertEqual(repaired["2"]["class_type"], "Cosmos3TextEncode")
        self.assertEqual(repaired["2"]["_meta"]["title"], "Positive Prompt")
        self.assertEqual(repaired["2"]["inputs"]["prompt"], "old prompt")
        self.assertEqual(repaired["2"]["inputs"]["width"], 832)
        self.assertEqual(repaired["2"]["inputs"]["height"], 480)
        self.assertEqual(repaired["2"]["inputs"]["text_encoder"], ["1", 1])
        self.assertEqual(repaired["4"]["inputs"]["prompt"], ["3", 0])
        self.assertEqual(repaired["4"]["inputs"]["width"], 832)
        self.assertNotIn("UNKNOWN", repaired["2"]["inputs"])
        workflow_queue.bind_text_prompt(repaired, text="a celadon teapot")
        self.assertEqual(repaired["2"]["inputs"]["prompt"], "a celadon teapot")
        self.assertEqual(repaired["4"]["inputs"]["prompt"], ["3", 0])

    def test_cosmos3_text_bind_uses_prompt_even_without_named_widget(self):
        prompt = {
            "2": {
                "class_type": "Cosmos3TextEncode",
                "inputs": {"UNKNOWN": "old", "text_encoder": ["1", 1]},
                "_meta": {"title": "Positive Prompt"},
            }
        }
        workflow_queue.bind_text_prompt(prompt, text="a celadon teapot")
        self.assertEqual(prompt["2"]["inputs"]["prompt"], "a celadon teapot")

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

    def test_bind_number_inputs_flux2_random_noise_and_scheduler(self):
        prompt = {
            "25": {
                "class_type": "RandomNoise",
                "inputs": {"noise_seed": 1, "noise_seed_control": "randomize"},
            },
            "47": {
                "class_type": "EmptyFlux2LatentImage",
                "inputs": {"width": 512, "height": 512, "batch_size": 1},
            },
            "48": {
                "class_type": "Flux2Scheduler",
                "inputs": {"steps": 20, "width": 512, "height": 512},
            },
        }
        workflow_queue.bind_number_inputs(
            prompt,
            {"seed": 99, "steps": 8, "width": 1024, "height": 768},
        )
        self.assertEqual(prompt["25"]["inputs"]["noise_seed"], 99)
        self.assertEqual(prompt["47"]["inputs"]["width"], 1024)
        self.assertEqual(prompt["47"]["inputs"]["height"], 768)
        self.assertEqual(prompt["48"]["inputs"]["steps"], 8)
        self.assertEqual(prompt["48"]["inputs"]["width"], 1024)

    def test_bind_number_inputs_ideogram4_scheduler(self):
        prompt = {
            "18": {
                "class_type": "RandomNoise",
                "inputs": {"noise_seed": 1, "noise_seed_control": "randomize"},
            },
            "11": {
                "class_type": "EmptyFlux2LatentImage",
                "inputs": {"width": 512, "height": 512, "batch_size": 1},
            },
            "17": {
                "class_type": "Ideogram4Scheduler",
                "inputs": {"steps": 20, "width": 512, "height": 512, "mu": 0.0, "std": 1.0},
            },
        }
        workflow_queue.bind_number_inputs(
            prompt,
            {"seed": 42, "steps": 12, "width": 768, "height": 1024},
        )
        self.assertEqual(prompt["18"]["inputs"]["noise_seed"], 42)
        self.assertEqual(prompt["11"]["inputs"]["width"], 768)
        self.assertEqual(prompt["11"]["inputs"]["height"], 1024)
        self.assertEqual(prompt["17"]["inputs"]["steps"], 12)
        self.assertEqual(prompt["17"]["inputs"]["width"], 768)
        self.assertEqual(prompt["17"]["inputs"]["height"], 1024)
        self.assertEqual(prompt["17"]["inputs"]["mu"], 0.0)

    def test_bind_cosmos3_text_scheduler_guider_and_size(self):
        prompt = {
            "2": {
                "class_type": "Cosmos3TextEncode",
                "inputs": {"prompt": "old", "width": 832, "height": 480},
                "_meta": {"title": "Positive Prompt"},
            },
            "4": {
                "class_type": "Cosmos3TextEncode",
                "inputs": {"prompt": ["3", 0], "width": 832, "height": 480},
                "_meta": {"title": "Negative Prompt"},
            },
            "5": {
                "class_type": "Cosmos3EmptyLatentVideo",
                "inputs": {"width": 832, "height": 480, "length": 93},
            },
            "6": {"class_type": "CFGGuider", "inputs": {"cfg": 6.0, "model": ["1", 0]}},
            "16": {
                "class_type": "DualModelGuider",
                "inputs": {"cfg": 3.5, "model": ["1", 0]},
            },
            "7": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1}},
            "9": {
                "class_type": "Cosmos3Scheduler",
                "inputs": {"steps": 35, "flow_shift": 5.0, "denoise": 1.0},
            },
            "15": {
                "class_type": "Cosmos3ImageToVideo",
                "inputs": {"width": 832, "height": 480, "length": 93},
            },
        }
        workflow_queue.bind_text_prompt(prompt, text="a celadon teapot")
        workflow_queue.bind_number_inputs(
            prompt,
            {"seed": 99, "steps": 20, "cfg": 4.5, "width": 1024, "height": 576},
        )
        self.assertEqual(prompt["2"]["inputs"]["prompt"], "a celadon teapot")
        self.assertEqual(prompt["4"]["inputs"]["prompt"], ["3", 0])
        self.assertEqual(prompt["7"]["inputs"]["noise_seed"], 99)
        self.assertEqual(prompt["9"]["inputs"]["steps"], 20)
        self.assertEqual(prompt["9"]["inputs"]["flow_shift"], 5.0)
        self.assertEqual(prompt["6"]["inputs"]["cfg"], 4.5)
        self.assertEqual(prompt["16"]["inputs"]["cfg"], 4.5)
        self.assertEqual(prompt["5"]["inputs"]["width"], 1024)
        self.assertEqual(prompt["5"]["inputs"]["height"], 576)
        self.assertEqual(prompt["2"]["inputs"]["width"], 1024)
        self.assertEqual(prompt["4"]["inputs"]["width"], 1024)
        self.assertEqual(prompt["4"]["inputs"]["height"], 576)
        self.assertEqual(prompt["15"]["inputs"]["width"], 1024)
        self.assertEqual(prompt["15"]["inputs"]["height"], 576)

    def test_inspect_cosmos3_ui_binds_prompt(self):
        payload = json.loads(
            (ROOT / "examples" / "cosmos3-nano-t2v.json").read_text(encoding="utf-8")
        )
        inspect = workflow_queue.inspect_workflow(payload)
        text_binds = [
            item["bind"]
            for item in inspect["nodes"]
            if item["class_type"] == "Cosmos3TextEncode"
        ]
        self.assertEqual(text_binds, ["prompt", "negative"])
        self.assertEqual(
            next(item["bind"] for item in inspect["nodes"] if item["class_type"] == "SaveVideo"),
            "save",
        )

    def test_to_api_prompt_passthrough(self):
        payload = {"1": {"class_type": "SaveImage", "inputs": {}}}
        self.assertEqual(workflow_queue.to_api_prompt(None, payload), payload)

    def test_queue_prompt_ids_reads_running_and_pending(self):
        ids = workflow_queue.queue_prompt_ids(
            {
                "queue_running": [[0, "abc", {}]],
                "queue_pending": [(1, "def")],
            }
        )
        self.assertEqual(ids, {"abc", "def"})
        self.assertEqual(workflow_queue.queue_prompt_ids("nope"), set())
        self.assertEqual(workflow_queue.queue_prompt_ids({"queue_running": ["x"]}), set())

    def test_wait_history_fails_fast_when_prompt_never_enters_queue(self):
        clock = {"t": 0.0}

        def fake_http(url: str, payload=None, timeout: int = 120):
            del payload, timeout
            if url.endswith("/queue"):
                return {"queue_running": [], "queue_pending": []}
            return {}

        with (
            patch.object(workflow_queue, "http_json", fake_http),
            patch.object(
                workflow_queue.time,
                "sleep",
                lambda seconds: clock.__setitem__("t", clock["t"] + seconds),
            ),
            patch.object(workflow_queue.time, "time", lambda: clock["t"]),
        ):
            with self.assertRaisesRegex(RuntimeError, "never appeared"):
                workflow_queue.wait_history(
                    "http://comfy",
                    "missing-id",
                    timeout=120,
                    lost_after=4,
                )

    def test_wait_history_fails_fast_when_queued_prompt_vanishes(self):
        clock = {"t": 0.0}
        queue_calls = {"n": 0}

        def fake_http(url: str, payload=None, timeout: int = 120):
            del payload, timeout
            if url.endswith("/queue"):
                queue_calls["n"] += 1
                if queue_calls["n"] == 1:
                    return {"queue_running": [[0, "pid-1", {}]], "queue_pending": []}
                return {"queue_running": [], "queue_pending": []}
            return {}

        with (
            patch.object(workflow_queue, "http_json", fake_http),
            patch.object(
                workflow_queue.time,
                "sleep",
                lambda seconds: clock.__setitem__("t", clock["t"] + seconds),
            ),
            patch.object(workflow_queue.time, "time", lambda: clock["t"]),
        ):
            with self.assertRaisesRegex(RuntimeError, "left /queue"):
                workflow_queue.wait_history(
                    "http://comfy",
                    "pid-1",
                    timeout=120,
                    lost_after=4,
                )

    def test_history_view_items_reads_result_glb_path(self):
        history = {
            "status": {"status_str": "success"},
            "outputs": {
                "12": {"result": ["/workspace/output/TRELLIS2_studio_00001_.glb"]}
            },
        }
        items = workflow_queue.history_view_items(history)
        self.assertEqual(
            items,
            [
                {
                    "filename": "TRELLIS2_studio_00001_.glb",
                    "subfolder": "",
                    "type": "output",
                }
            ],
        )

    def test_history_view_items_reads_text_windows_glb(self):
        history = {
            "outputs": {"17": {"text": [r"C:\Users\me\output\pixal3d_demo.glb"]}}
        }
        items = workflow_queue.history_view_items(history)
        self.assertEqual(items[0]["filename"], "pixal3d_demo.glb")

    def test_history_view_items_dedupes_images_and_result(self):
        history = {
            "outputs": {
                "9": {
                    "images": [{"filename": "out.png", "type": "output"}],
                    "result": ["out.png"],
                }
            }
        }
        items = workflow_queue.history_view_items(history)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["filename"], "out.png")

    def test_download_outputs_fetches_result_glb(self):
        history = {
            "status": {"status_str": "success"},
            "outputs": {
                "12": {"result": ["/workspace/output/TRELLIS2_studio_00001_.glb"]}
            },
        }
        payload = b"glTF" + b"\x00" * 8

        class FakeResponse:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            with patch("workflow_queue.urllib.request.urlopen", return_value=FakeResponse()) as opener:
                saved = workflow_queue.download_outputs("http://comfy", history, dest)
            self.assertEqual([path.name for path in saved], ["TRELLIS2_studio_00001_.glb"])
            self.assertEqual(saved[0].read_bytes(), payload)
            opened = opener.call_args[0][0]
            self.assertIn("filename=TRELLIS2_studio_00001_.glb", opened)
            self.assertTrue(opened.startswith("http://comfy/view?"))

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


class ChromePathTests(unittest.TestCase):
    def test_comfy_chrome_override_wins_when_file_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            chrome = Path(directory) / "chrome.exe"
            chrome.write_text("", encoding="utf-8")
            with patch.dict(os.environ, {"COMFY_CHROME": str(chrome)}, clear=False):
                self.assertEqual(workflow_queue.chrome_executable(), str(chrome))

    def test_windows_edge_is_among_candidates(self):
        local = r"C:\Users\demo\AppData\Local"
        with patch.dict(os.environ, {"LOCALAPPDATA": local, "COMFY_CHROME": ""}, clear=False):
            paths = [str(item) for item in workflow_queue.chrome_search_paths()]
        self.assertTrue(
            any(
                item.replace("\\", "/").endswith("Microsoft/Edge/Application/msedge.exe")
                for item in paths
            )
        )
        self.assertTrue(
            any(
                item.replace("\\", "/").endswith("Google/Chrome/Application/chrome.exe")
                for item in paths
            )
        )
        self.assertIn("/usr/local/bin/google-chrome", paths)

    def test_missing_browser_returns_none(self):
        with (
            patch.dict(os.environ, {"COMFY_CHROME": "", "LOCALAPPDATA": ""}, clear=False),
            patch("workflow_queue.shutil.which", return_value=None),
            patch("pathlib.Path.is_file", return_value=False),
        ):
            self.assertIsNone(workflow_queue.chrome_executable())


if __name__ == "__main__":
    unittest.main()
