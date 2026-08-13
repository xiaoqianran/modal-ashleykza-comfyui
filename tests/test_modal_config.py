import unittest

from modal_config import ModalSettings, wants_latest_dependencies


class ModalSettingsTests(unittest.TestCase):
    def test_defaults_follow_modal_runtime_limits(self):
        settings = ModalSettings.from_env({})
        self.assertEqual(settings.ui_timeout_seconds, 24 * 60 * 60)
        self.assertEqual(settings.ui_startup_timeout_seconds, 15 * 60)
        self.assertEqual(settings.ui_scaledown_window_seconds, 5 * 60)
        self.assertEqual(settings.gpu, ("T4", "L4", "L40S", "RTX-PRO-6000"))
        self.assertEqual(settings.secret_name, "comfyui-creds")
        self.assertTrue(settings.base_nodes_enabled)
        self.assertFalse(settings.latest_dependencies)

    def test_parses_gpu_fallback_and_proxy_auth(self):
        settings = ModalSettings.from_env(
            {
                "MODAL_GPU": "L40S, H100",
                "COMFY_REQUIRE_PROXY_AUTH": "true",
                "COMFY_MAX_INPUTS": "16",
                "COMFY_TARGET_INPUTS": "8",
            }
        )
        self.assertEqual(settings.gpu, ("L40S", "H100"))
        self.assertTrue(settings.ui_requires_proxy_auth)
        self.assertEqual(settings.ui_max_inputs, 16)
        self.assertEqual(settings.ui_target_inputs, 8)

    def test_rejects_invalid_autoscaling_bounds(self):
        with self.assertRaisesRegex(ValueError, "COMFY_TARGET_INPUTS"):
            ModalSettings.from_env(
                {
                    "COMFY_MAX_INPUTS": "4",
                    "COMFY_TARGET_INPUTS": "5",
                }
            )

    def test_rejects_timeout_beyond_modal_maximum(self):
        with self.assertRaisesRegex(ValueError, "COMFY_TIMEOUT_SECONDS"):
            ModalSettings.from_env({"COMFY_TIMEOUT_SECONDS": "86401"})

    def test_modal_serve_defaults_to_latest_github_head(self):
        self.assertTrue(wants_latest_dependencies({}, ["modal", "serve", "comfyui_modal.py"]))
        self.assertFalse(wants_latest_dependencies({}, ["modal", "deploy", "comfyui_modal.py"]))
        self.assertTrue(wants_latest_dependencies({"COMFY_LATEST": "1"}, ["modal", "deploy"]))
        self.assertFalse(wants_latest_dependencies({"COMFY_LATEST": "0"}, ["modal", "serve"]))
        settings = ModalSettings.from_env({}, argv=["/usr/bin/modal", "serve", "comfyui_modal.py"])
        self.assertTrue(settings.latest_dependencies)


if __name__ == "__main__":
    unittest.main()
