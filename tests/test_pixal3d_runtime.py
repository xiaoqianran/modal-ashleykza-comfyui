import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import comfy_engine


class DummyProcess:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code

    def terminate(self):
        self.code = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.code = 0


def _lock() -> dict:
    return {
        "schema": 1,
        "custom_nodes": [{"id": "comfyui-kjnodes", "version": "1.0"}],
        "unresolved": [],
        "workflow": {"name": "demo.json", "sha256": "abc"},
        "models": [
            {
                "category": "vae",
                "filename": "ae.safetensors",
                "url": "https://example.com/ae.safetensors",
                "sha256": None,
                "source": "test",
            }
        ],
    }


class NattenWheelSpecTests(unittest.TestCase):
    def test_maps_ashley_torch211_cu128(self):
        self.assertEqual(
            comfy_engine.natten_wheel_spec("2.11.0+cu128"),
            "0.21.6+torch2110cu128",
        )

    def test_maps_older_and_newer_official_tags(self):
        self.assertEqual(
            comfy_engine.natten_wheel_spec("2.10.0+cu128"),
            "0.21.6+torch2100cu128",
        )
        self.assertEqual(
            comfy_engine.natten_wheel_spec("2.9.0+cu128"),
            "0.21.6+torch290cu128",
        )
        self.assertEqual(
            comfy_engine.natten_wheel_spec("2.12.0+cu126", natten_version="0.21.6"),
            "0.21.6+torch2120cu126",
        )

    def test_rejects_unknown_torch_version(self):
        with self.assertRaises(ValueError):
            comfy_engine.natten_wheel_spec("2.11.0.dev0+cu128")


class FlashAttnWheelTests(unittest.TestCase):
    def test_ashley_py312_torch211_url(self):
        url = comfy_engine.flash_attn_wheel_url("3.12.3", "2.11.0+cu128")
        self.assertIsNotNone(url)
        assert url is not None
        self.assertIn("v2.8.3-cu12-torch2.11", url)
        self.assertIn("cp312-cp312-linux_x86_64.whl", url)

    def test_missing_for_other_torch(self):
        self.assertIsNone(comfy_engine.flash_attn_wheel_url("3.12", "2.10.0+cu128"))


class RequirementsFilterTests(unittest.TestCase):
    def test_strips_natten_pin(self):
        text = "einops\nnatten==0.21.6\nmoge @ git+https://example.com/moge.git\n"
        filtered = comfy_engine.requirements_without_packages(text, frozenset({"natten"}))
        self.assertNotIn("natten", filtered)
        self.assertIn("einops", filtered)
        self.assertIn("moge", filtered)

    def test_reads_natten_pin(self):
        self.assertEqual(
            comfy_engine.natten_requirement_version("einops\nnatten==0.21.6\n"),
            "0.21.6",
        )


class InstallNattenWheelTests(unittest.TestCase):
    def test_pip_uses_only_binary_and_official_index(self):
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)

        with (
            patch.object(comfy_engine, "_python_text", return_value="2.11.0+cu128"),
            patch.object(comfy_engine, "_run", fake_run),
            patch.object(comfy_engine, "_module_available", return_value=True),
        ):
            self.assertTrue(
                comfy_engine._install_natten_wheel("/ComfyUI/venv/bin/python3")
            )
        self.assertEqual(len(calls), 1)
        self.assertIn("--only-binary=:all:", calls[0])
        self.assertIn("natten==0.21.6+torch2110cu128", calls[0])
        self.assertIn(comfy_engine.NATTEN_WHEEL_INDEX, calls[0])
        self.assertNotIn("natten==0.21.6", calls[0])


class ApplyVolumeLaunchWheelOrderTests(unittest.TestCase):
    def test_installs_wheels_before_cnr(self):
        order: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "storage"
            workspace = root / "workspace"
            comfy_root = root / "ComfyUI"
            comfy_root.mkdir()
            (comfy_root / "main.py").write_text("#\n", encoding="utf-8")
            target = storage / "vae" / "ae.safetensors"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"model")
            lock = _lock()
            lock["custom_nodes"] = [{"id": "Pixal3D-ComfyUI", "version": "0.2.4"}]
            comfy_engine.persist_launch_state(
                storage,
                mode="workflow",
                workflow="demo.json",
                workflow_lock=lock,
            )

            def installer(*_args, **_kwargs):
                order.append("cnr")
                return ["Pixal3D-ComfyUI"]

            with (
                patch.object(
                    comfy_engine,
                    "ensure_pixal3d_prebuilt_wheels",
                    side_effect=lambda *_a, **_k: order.append("wheels") or True,
                ),
                patch.object(
                    comfy_engine,
                    "ensure_pixal3d_runtime",
                    side_effect=lambda *_a, **_k: order.append("runtime") or False,
                ),
            ):
                comfy_engine.apply_volume_launch(
                    storage_root=storage,
                    workspace=workspace,
                    comfy_root=comfy_root,
                    default_profile="base",
                    default_install_lock_nodes=True,
                    start_fn=lambda **_kwargs: DummyProcess(),
                    wait_fn=lambda **_kwargs: None,
                    install_nodes=installer,
                )
        self.assertEqual(order, ["wheels", "cnr", "runtime"])


if __name__ == "__main__":
    unittest.main()
