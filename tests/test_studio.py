import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio.keys import mask_secret, save_keys
from studio.modal_ops import _container_rows, is_billable_gpu_app
from studio.server import _generate_batch, _split_prompts, wants_keep_gpu


class MaskSecretTests(unittest.TestCase):
    def test_masks_long_token(self):
        self.assertEqual(mask_secret("hf_abcdefghijklmnop"), "hf_a…mnop")

    def test_empty(self):
        self.assertEqual(mask_secret(""), "")


class SplitPromptTests(unittest.TestCase):
    def test_one_per_line(self):
        self.assertEqual(_split_prompts("a\nb\n"), ["a", "b"])

    def test_separator(self):
        text = "line one\nstill one\n---\nsecond"
        self.assertEqual(_split_prompts(text), ["line one\nstill one", "second"])


class SaveKeysTests(unittest.TestCase):
    def test_writes_gitignored_env(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".studio.env"
            with patch("studio.keys.STUDIO_ENV_PATH", path):
                save_keys({"HF_TOKEN": "hf_test_token_value"})
            text = path.read_text(encoding="utf-8")
            self.assertIn("HF_TOKEN=hf_test_token_value", text)
            dumped = json.dumps({"studio": text})
            self.assertNotIn("MODAL_TOKEN_SECRET=", dumped)


class GpuReleaseTests(unittest.TestCase):
    def test_keep_gpu_is_opt_in(self):
        self.assertFalse(wants_keep_gpu({}))
        self.assertFalse(wants_keep_gpu({"keep_gpu": False}))
        self.assertFalse(wants_keep_gpu({"keep_gpu": "0"}))
        self.assertTrue(wants_keep_gpu({"keep_gpu": True}))
        self.assertTrue(wants_keep_gpu({"keep_gpu": "yes"}))

    def test_generate_stops_serve_unless_keep_gpu(self):
        payload = {"prompts": ["a teapot"]}
        with (
            patch(
                "studio.server._run_generate_batch",
                return_value={"ok": True, "count": 1, "results": []},
            ),
            patch(
                "studio.server.stop_serve",
                return_value={"stopped": True, "pid": 1, "containers": []},
            ) as stop,
        ):
            _generate_batch("job-a", payload)
            stop.assert_called_once()
            stop.reset_mock()
            _generate_batch("job-b", {**payload, "keep_gpu": True})
            stop.assert_not_called()

    def test_hydrate_app_is_not_a_billable_gpu_target(self):
        self.assertTrue(is_billable_gpu_app("comfyui-ashleykza-cu128"))
        self.assertFalse(is_billable_gpu_app("comfyui-ashleykza-cu128-hydrate"))
        rows = _container_rows(
            '[{"container_id":"ta-1","app_name":"comfyui-ashleykza-cu128"}]'
        )
        self.assertEqual(rows[0]["container_id"], "ta-1")


if __name__ == "__main__":
    unittest.main()
