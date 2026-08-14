import unittest

from modal_config import ModalSettings, wants_latest_dependencies


class ModalSettingsTests(unittest.TestCase):
    def test_defaults_follow_modal_runtime_limits(self):
        settings = ModalSettings.from_env({})
        self.assertEqual(settings.ui_timeout_seconds, 24 * 60 * 60)
        self.assertEqual(settings.ui_startup_timeout_seconds, 15 * 60)
        self.assertEqual(settings.ui_scaledown_window_seconds, 5)
        self.assertEqual(settings.gpu, ("L40S",))
        self.assertEqual(settings.secret_name, "comfyui-creds")
        self.assertFalse(settings.base_nodes_enabled)
        self.assertFalse(settings.install_nodes)
        self.assertTrue(settings.install_lock_nodes)
        self.assertEqual(settings.launch_mode, "profile")
        self.assertEqual(settings.profile_name, "base")
        self.assertEqual(settings.workflow_source, "")
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

    def test_latest_only_when_explicitly_requested(self):
        self.assertFalse(wants_latest_dependencies({}, ["modal", "serve", "comfyui_modal.py"]))
        self.assertFalse(wants_latest_dependencies({}, ["modal", "deploy", "comfyui_modal.py"]))
        self.assertTrue(wants_latest_dependencies({"COMFY_LATEST": "1"}, ["modal", "deploy"]))
        self.assertFalse(wants_latest_dependencies({"COMFY_LATEST": "0"}, ["modal", "serve"]))
        settings = ModalSettings.from_env({}, argv=["/usr/bin/modal", "serve", "comfyui_modal.py"])
        self.assertFalse(settings.latest_dependencies)
        self.assertTrue(settings.memory_snapshot)
        self.assertTrue(settings.gpu_snapshot)
        self.assertEqual(settings.models_volume_name, "comfyui-ashleykza-models")
        self.assertEqual(settings.storage_root, "/mnt/comfy-storage")
        self.assertEqual(settings.hydrate_workers, 4)

    def test_idle_release_does_not_keep_warm_containers(self):
        from modal_config import CHEAP_GPUS, idle_release_kwargs

        settings = ModalSettings.from_env({})
        self.assertTrue(set(settings.gpu) <= CHEAP_GPUS)
        kwargs = idle_release_kwargs(settings)
        self.assertEqual(kwargs["scaledown_window"], 5)
        self.assertEqual(kwargs["min_containers"], 0)
        self.assertEqual(kwargs["buffer_containers"], 0)

    def test_parses_storage_and_hydrate_settings(self):
        settings = ModalSettings.from_env(
            {
                "MODAL_MODELS_VOLUME": "my-models",
                "COMFY_STORAGE_ROOT": "/models",
                "COMFY_HYDRATE_WORKERS": "8",
            }
        )
        self.assertEqual(settings.models_volume_name, "my-models")
        self.assertEqual(settings.storage_root, "/models")
        self.assertEqual(settings.hydrate_workers, 8)

    def test_parses_snapshot_flags(self):
        settings = ModalSettings.from_env(
            {
                "COMFY_MEMORY_SNAPSHOT": "0",
                "COMFY_GPU_SNAPSHOT": "0",
            }
        )
        self.assertFalse(settings.memory_snapshot)
        self.assertFalse(settings.gpu_snapshot)
        forced_off = ModalSettings.from_env(
            {
                "COMFY_MEMORY_SNAPSHOT": "0",
                "COMFY_GPU_SNAPSHOT": "1",
            }
        )
        self.assertFalse(forced_off.gpu_snapshot)

    def test_workflow_mode_from_env_and_argv(self):
        from_env = ModalSettings.from_env(
            {
                "COMFY_WORKFLOW": "examples/z-image-base.json",
                "COMFY_PROFILE": "qwen-image",
            }
        )
        self.assertEqual(from_env.launch_mode, "workflow")
        self.assertEqual(from_env.workflow_source, "examples/z-image-base.json")
        self.assertEqual(
            from_env.workflow_lock_source,
            "examples/z-image-base.lock.json",
        )
        self.assertEqual(from_env.profile_name, "qwen-image")

        from_argv = ModalSettings.from_env(
            {},
            argv=["modal", "serve", "comfyui_modal.py", "--workflow", "wf.json"],
        )
        self.assertEqual(from_argv.launch_mode, "workflow")
        self.assertEqual(from_argv.workflow_source, "wf.json")
        self.assertEqual(from_argv.workflow_lock_source, "wf.lock.json")

    def test_install_nodes_is_opt_in(self):
        self.assertFalse(ModalSettings.from_env({}).install_nodes)
        enabled = ModalSettings.from_env({"COMFY_INSTALL_NODES": "1"})
        self.assertTrue(enabled.install_nodes)
        flagged = ModalSettings.from_env(
            {},
            argv=["modal", "serve", "comfyui_modal.py", "--install-nodes"],
        )
        self.assertTrue(flagged.install_nodes)

    def test_lock_nodes_install_by_default(self):
        self.assertTrue(ModalSettings.from_env({}).install_lock_nodes)
        skipped = ModalSettings.from_env({"COMFY_INSTALL_LOCK_NODES": "0"})
        self.assertFalse(skipped.install_lock_nodes)
        skipped_argv = ModalSettings.from_env(
            {},
            argv=["modal", "serve", "comfyui_modal.py", "--skip-lock-nodes"],
        )
        self.assertFalse(skipped_argv.install_lock_nodes)


if __name__ == "__main__":
    unittest.main()
