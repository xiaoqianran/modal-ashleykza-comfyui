import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio.keys import mask_secret, save_keys
from studio.modal_ops import (
    _container_rows,
    _first_app_url,
    gpu_mode,
    is_billable_gpu_app,
    serve_url,
    start_gpu,
    stop_gpu,
)
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

    def test_chmod_oserror_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".studio.env"
            with (
                patch("studio.keys.STUDIO_ENV_PATH", path),
                patch("pathlib.Path.chmod", side_effect=OSError("unsupported")),
            ):
                save_keys({"HF_TOKEN": "hf_test_token_value"})
            self.assertIn("HF_TOKEN=hf_test_token_value", path.read_text(encoding="utf-8"))


class StudioLaunchTests(unittest.TestCase):
    def test_parse_args_defaults_open_browser(self):
        from studio.server import parse_args, studio_url

        args = parse_args([])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8787)
        self.assertFalse(args.no_browser)
        self.assertEqual(studio_url(args.host, args.port), "http://127.0.0.1:8787")

    def test_parse_args_no_browser(self):
        from studio.server import parse_args

        args = parse_args(["--no-browser", "--port", "8790"])
        self.assertTrue(args.no_browser)
        self.assertEqual(args.port, 8790)


class GpuReleaseTests(unittest.TestCase):
    def test_keep_gpu_is_opt_in(self):
        self.assertFalse(wants_keep_gpu({}))
        self.assertFalse(wants_keep_gpu({"keep_gpu": False}))
        self.assertFalse(wants_keep_gpu({"keep_gpu": "0"}))
        self.assertTrue(wants_keep_gpu({"keep_gpu": True}))
        self.assertTrue(wants_keep_gpu({"keep_gpu": "yes"}))

    def test_generate_stops_gpu_unless_keep_gpu(self):
        payload = {"prompts": ["a teapot"]}
        with (
            patch(
                "studio.server._run_generate_batch",
                return_value={"ok": True, "count": 1, "results": []},
            ),
            patch(
                "studio.server.stop_gpu",
                return_value={"stopped": True, "pid": None, "containers": []},
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

    def test_studio_reads_modal_app_name(self):
        with patch.dict(os.environ, {"MODAL_APP_NAME": "comfyui-other"}, clear=False):
            self.assertTrue(is_billable_gpu_app("comfyui-other"))
            self.assertFalse(is_billable_gpu_app("comfyui-other-hydrate"))
            self.assertEqual(
                serve_url("weiranzhiqian", dev=False),
                "https://weiranzhiqian--comfyui-other-ui-ui.modal.run",
            )

    def test_default_gpu_mode_is_deploy_and_url_has_no_dev_suffix(self):
        self.assertEqual(gpu_mode(), "deploy")
        self.assertNotIn("-dev", serve_url("weiranzhiqian", dev=False))
        self.assertIn("-dev", serve_url("weiranzhiqian", dev=True))
        self.assertEqual(
            _first_app_url(
                "dev https://ws--comfyui-ashleykza-cu128-ui-ui-dev.modal.run\n"
                "prod https://ws--comfyui-ashleykza-cu128-ui-ui.modal.run\n"
            ),
            "https://ws--comfyui-ashleykza-cu128-ui-ui.modal.run",
        )

    def test_start_gpu_runs_modal_deploy_not_serve(self):
        calls: list[list[str]] = []

        class Result:
            def __init__(self, stdout=""):
                self.stdout = stdout
                self.stderr = ""
                self.returncode = 0

        def fake_run(args, **_kwargs):
            calls.append(list(args))
            if "profile" in args:
                return Result("weiranzhiqian\n")
            if "deploy" in args:
                return Result(
                    "https://weiranzhiqian--comfyui-ashleykza-cu128-ui-ui.modal.run\n"
                )
            if "container" in args:
                return Result("[]\n")
            return Result()

        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            with (
                patch.dict(os.environ, {"STUDIO_GPU_MODE": "deploy"}, clear=False),
                patch("studio.modal_ops.STATE_DIR", state_dir),
                patch("studio.modal_ops.STATE_PATH", state_dir / "state.json"),
                patch("studio.modal_ops._run", fake_run),
                patch(
                    "studio.modal_ops.load_catalog",
                    return_value={"gpu": "L40S", "gpu_choices": ["L40S"]},
                ),
                patch("studio.modal_ops.subprocess_env", return_value={"PATH": "/bin"}),
                patch("studio.modal_ops.modal_bin", return_value="modal"),
            ):
                result = start_gpu("z-image", "L40S")
        deploy = [cmd for cmd in calls if "deploy" in cmd]
        self.assertTrue(deploy)
        self.assertIn("comfyui_modal.py", deploy[0])
        self.assertFalse(any("serve" in cmd for cmd in calls if "profile" not in cmd))
        self.assertEqual(result["gpu_mode"], "deploy")
        self.assertIsNone(result["pid"])
        self.assertNotIn("-dev", result["base_url"])

    def test_start_gpu_serve_opt_in_still_uses_modal_serve(self):
        import studio.modal_ops as modal_ops

        class FakeProc:
            pid = 4242

            def poll(self):
                return None

            def send_signal(self, _sig):
                return None

            def wait(self, timeout=None):
                return 0

            def kill(self):
                return None

        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            try:
                with (
                    patch.dict(os.environ, {"STUDIO_GPU_MODE": "serve"}, clear=False),
                    patch("studio.modal_ops.STATE_DIR", state_dir),
                    patch("studio.modal_ops.STATE_PATH", state_dir / "state.json"),
                    patch(
                        "studio.modal_ops.load_catalog",
                        return_value={"gpu": "L40S", "gpu_choices": ["L40S"]},
                    ),
                    patch("studio.modal_ops.subprocess_env", return_value={"PATH": "/bin"}),
                    patch("studio.modal_ops.modal_bin", return_value="modal"),
                    patch(
                        "studio.modal_ops.current_workspace",
                        return_value="weiranzhiqian",
                    ),
                    patch("studio.modal_ops.subprocess.Popen", return_value=FakeProc()),
                    patch("studio.modal_ops.threading.Thread"),
                ):
                    result = start_gpu("z-image", "L40S")
            finally:
                modal_ops._SERVE_PROC = None
        self.assertEqual(result["gpu_mode"], "serve")
        self.assertEqual(result["pid"], 4242)
        self.assertIn("-dev", result["base_url"])

    def test_stop_gpu_stops_containers_not_the_app(self):
        calls: list[list[str]] = []

        class Result:
            stdout = "[]"
            stderr = ""
            returncode = 0

        def fake_run(args, **_kwargs):
            calls.append(list(args))
            return Result()

        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            with (
                patch("studio.modal_ops.STATE_DIR", state_dir),
                patch("studio.modal_ops.STATE_PATH", state_dir / "state.json"),
                patch("studio.modal_ops._run", fake_run),
                patch("studio.modal_ops.subprocess_env", return_value={"PATH": "/bin"}),
                patch("studio.modal_ops.modal_bin", return_value="modal"),
            ):
                stop_gpu()
        joined = [" ".join(cmd) for cmd in calls]
        self.assertTrue(any("container" in text for text in joined))
        self.assertFalse(any("app stop" in text for text in joined))


if __name__ == "__main__":
    unittest.main()
