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


class Sparse3dWheelUrlTests(unittest.TestCase):
    def test_ashley_cp312_torch211_cu128_urls(self):
        rows = comfy_engine.sparse_3d_wheel_urls("3.12.3", "2.11.0+cu128")
        labels = [item[0] for item in rows]
        self.assertEqual(labels, ["flex_gemm", "cumesh", "o_voxel"])
        for _label, _imports, url in rows:
            self.assertIn("PozzettiAndrea/cuda-wheels", url)
            self.assertIn("cu128torch2.11", url)
            self.assertIn("cp312", url)
            self.assertIn("%2B", url)
        with_drtk = comfy_engine.sparse_3d_wheel_urls(
            "3.12.3", "2.11.0+cu128", include_drtk=True
        )
        self.assertEqual([item[0] for item in with_drtk], ["flex_gemm", "cumesh", "o_voxel", "drtk"])

    def test_missing_for_other_python_or_cuda(self):
        self.assertEqual(comfy_engine.sparse_3d_wheel_urls("3.13.0", "2.11.0+cu128"), ())
        self.assertEqual(comfy_engine.sparse_3d_wheel_urls("3.12.3", "2.11.0+cu130"), ())
        self.assertEqual(comfy_engine.sparse_3d_wheel_urls("3.12.3", "2.10.0+cu128"), ())


class InstallSparse3dWheelsTests(unittest.TestCase):
    def test_installs_python_deps_without_torch(self):
        calls: list[list[str]] = []
        cuda = {
            "flex_gemm_ap",
            "flex_gemm",
            "cumesh_vb",
            "cumesh",
            "o_voxel_vb_ap",
            "o_voxel",
        }

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))

        with (
            patch.object(
                comfy_engine,
                "_python_text",
                side_effect=["3.12.3", "2.11.0+cu128"],
            ),
            patch.object(comfy_engine, "_run", fake_run),
            patch.object(
                comfy_engine,
                "_module_available",
                lambda name, _p: name in cuda,
            ),
        ):
            self.assertTrue(
                comfy_engine._install_sparse_3d_prebuilt_wheels(
                    "/ComfyUI/venv/bin/python3", include_drtk=False
                )
            )
        dep_calls = [cmd for cmd in calls if "pip" in cmd and "trimesh" in cmd]
        self.assertEqual(len(dep_calls), 1)
        self.assertIn("plyfile", dep_calls[0])
        self.assertIn("easydict", dep_calls[0])
        self.assertNotIn("torch", dep_calls[0])
        self.assertFalse(any(str(cmd[-1]).endswith(".whl") for cmd in calls))


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

            runtime_kwargs: list[dict] = []
            wheel_kwargs: list[dict] = []
            with (
                patch.object(
                    comfy_engine,
                    "ensure_pixal3d_prebuilt_wheels",
                    side_effect=lambda *_a, **kwargs: (
                        order.append("wheels") or wheel_kwargs.append(kwargs) or True
                    ),
                ),
                patch.object(
                    comfy_engine,
                    "ensure_pixal3d_runtime",
                    side_effect=lambda *_a, **kwargs: (
                        order.append("runtime") or runtime_kwargs.append(kwargs) or False
                    ),
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
        self.assertEqual(wheel_kwargs[0].get("include_attention"), True)
        self.assertEqual(wheel_kwargs[0].get("include_drtk"), True)
        self.assertEqual(runtime_kwargs[0].get("include_pixal3d"), True)
        self.assertEqual(runtime_kwargs[0].get("allow_source_compile"), False)


class Trellis2LaunchOrderTests(unittest.TestCase):
    def test_installs_wheels_before_cnr_then_runtime(self):
        order: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "storage"
            workspace = root / "workspace"
            comfy_root = root / "ComfyUI"
            comfy_root.mkdir()
            (comfy_root / "main.py").write_text("#\n", encoding="utf-8")
            target = storage / "microsoft" / "TRELLIS.2-4B" / "pipeline.json"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"model")
            lock = {
                "schema": 1,
                "custom_nodes": [
                    {
                        "id": "ComfyUI-Trellis2",
                        "version": "main",
                        "url": "https://github.com/visualbruno/ComfyUI-Trellis2.git",
                    }
                ],
                "unresolved": [],
                "workflow": {"name": "trellis2.json", "sha256": "abc"},
                "models": [
                    {
                        "category": "microsoft",
                        "filename": "TRELLIS.2-4B/pipeline.json",
                        "url": "https://example.com/pipeline.json",
                        "sha256": None,
                        "source": "test",
                    }
                ],
            }
            comfy_engine.persist_launch_state(
                storage,
                mode="workflow",
                workflow="demo.json",
                workflow_lock=lock,
            )

            def installer(*_args, **_kwargs):
                order.append("cnr")
                return ["ComfyUI-Trellis2"]

            runtime_kwargs: list[dict] = []
            wheel_kwargs: list[dict] = []
            leftover = workspace / "custom_nodes" / "Pixal3D-ComfyUI"
            leftover.mkdir(parents=True)
            (leftover / "requirements.txt").write_text("moge\n", encoding="utf-8")
            with (
                patch.object(
                    comfy_engine,
                    "ensure_pixal3d_prebuilt_wheels",
                    side_effect=lambda *_a, **kwargs: (
                        order.append("wheels") or wheel_kwargs.append(kwargs) or True
                    ),
                ),
                patch.object(
                    comfy_engine,
                    "ensure_pixal3d_runtime",
                    side_effect=lambda *_a, **kwargs: (
                        order.append("runtime") or runtime_kwargs.append(kwargs) or False
                    ),
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
        self.assertEqual(wheel_kwargs[0].get("include_attention"), False)
        self.assertEqual(wheel_kwargs[0].get("include_drtk"), False)
        self.assertEqual(runtime_kwargs[0].get("include_pixal3d"), False)
        self.assertEqual(runtime_kwargs[0].get("allow_source_compile"), False)


class Sparse3dRuntimeWithoutPixal3dTests(unittest.TestCase):
    def test_wheel_miss_raises_without_source_compile(self):
        calls: list[list[str]] = []

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comfy_root = root / "ComfyUI"
            custom_nodes = root / "custom_nodes"
            comfy_root.mkdir()
            (custom_nodes / "ComfyUI-Trellis2").mkdir(parents=True)
            with (
                patch.object(comfy_engine, "_comfy_python", return_value="/usr/bin/python3"),
                patch.object(comfy_engine, "_run", fake_run),
                patch.object(comfy_engine, "_module_available", return_value=False),
                patch.object(comfy_engine, "_module_import_error", return_value="missing"),
                patch.object(comfy_engine, "_ensure_cuda_build_tools"),
                patch.object(comfy_engine, "ensure_pixal3d_prebuilt_wheels", return_value=False),
                patch.object(comfy_engine, "_install_flash_attn_wheel", return_value=True),
                patch.object(comfy_engine, "_install_sparse_3d_prebuilt_wheels", return_value=False),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    comfy_engine.ensure_pixal3d_runtime(comfy_root, custom_nodes)
        self.assertIn("GPU source compile is disabled", str(ctx.exception))
        self.assertIn("o_voxel", str(ctx.exception))
        joined = " ".join(" ".join(cmd) for cmd in calls)
        self.assertNotIn("FlexGEMM", joined)
        self.assertNotIn("TRELLIS.2.git", joined)

    def test_opt_in_source_compile_skips_drtk(self):
        calls: list[list[str]] = []
        available: set[str] = set()

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if cmd and cmd[0] == "git":
                Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
            if "pip" in cmd:
                dest = cmd[-1]
                if dest.endswith("flex_gemm"):
                    available.update({"flex_gemm_ap", "flex_gemm"})
                elif dest.endswith("cumesh"):
                    available.update({"cumesh_vb", "cumesh"})
                elif dest.endswith("o-voxel") or dest.endswith("o_voxel"):
                    available.update({"o_voxel_vb_ap", "o_voxel"})
                elif dest.endswith("DRTK") or dest.endswith("drtk"):
                    available.add("drtk")

        def fake_available(name, _python):
            return name in available

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comfy_root = root / "ComfyUI"
            custom_nodes = root / "custom_nodes"
            comfy_root.mkdir()
            (custom_nodes / "ComfyUI-Trellis2").mkdir(parents=True)
            with (
                patch.object(comfy_engine, "_comfy_python", return_value="/usr/bin/python3"),
                patch.object(comfy_engine, "_run", fake_run),
                patch.object(comfy_engine, "_module_available", fake_available),
                patch.object(comfy_engine, "_ensure_cuda_build_tools"),
                patch.object(comfy_engine, "ensure_pixal3d_prebuilt_wheels", return_value=False),
                patch.object(comfy_engine, "_install_flash_attn_wheel", return_value=True),
                patch.object(comfy_engine, "_install_sparse_3d_prebuilt_wheels", return_value=False),
            ):
                changed = comfy_engine.ensure_pixal3d_runtime(
                    comfy_root,
                    custom_nodes,
                    allow_source_compile=True,
                )
        self.assertTrue(changed)
        joined = " ".join(" ".join(cmd) for cmd in calls)
        self.assertIn("FlexGEMM", joined)
        self.assertIn("CuMesh", joined)
        self.assertIn("TRELLIS.2.git", joined)
        self.assertNotIn("DRTK", joined)

    def test_uses_prebuilt_wheels_instead_of_compile(self):
        calls: list[list[str]] = []
        available: set[str] = set()

        def fake_wheels(_python, *, include_drtk):
            available.update(
                {"flex_gemm_ap", "flex_gemm", "cumesh_vb", "cumesh", "o_voxel_vb_ap", "o_voxel"}
            )
            if include_drtk:
                available.add("drtk")
            return True

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comfy_root = root / "ComfyUI"
            custom_nodes = root / "custom_nodes"
            comfy_root.mkdir()
            (custom_nodes / "ComfyUI-Trellis2").mkdir(parents=True)
            with (
                patch.object(comfy_engine, "_comfy_python", return_value="/usr/bin/python3"),
                patch.object(comfy_engine, "_run", fake_run),
                patch.object(comfy_engine, "_module_available", lambda name, _p: name in available),
                patch.object(comfy_engine, "_ensure_cuda_build_tools"),
                patch.object(comfy_engine, "ensure_pixal3d_prebuilt_wheels", return_value=False),
                patch.object(comfy_engine, "_install_flash_attn_wheel", return_value=True),
                patch.object(comfy_engine, "_install_sparse_3d_prebuilt_wheels", fake_wheels),
            ):
                changed = comfy_engine.ensure_pixal3d_runtime(comfy_root, custom_nodes)
        self.assertTrue(changed)
        joined = " ".join(" ".join(cmd) for cmd in calls)
        self.assertNotIn("FlexGEMM", joined)
        self.assertNotIn("CuMesh", joined)
        self.assertNotIn("TRELLIS.2.git", joined)
        self.assertNotIn("DRTK", joined)

    def test_ignores_leftover_pixal3d_requirements_and_drtk(self):
        calls: list[list[str]] = []
        available: set[str] = {
            "flex_gemm_ap",
            "flex_gemm",
            "cumesh_vb",
            "cumesh",
            "o_voxel_vb_ap",
            "o_voxel",
        }

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comfy_root = root / "ComfyUI"
            custom_nodes = root / "custom_nodes"
            leftover = custom_nodes / "Pixal3D-ComfyUI"
            leftover.mkdir(parents=True)
            (leftover / "requirements.txt").write_text("moge\nnatten==0.21.6\n", encoding="utf-8")
            comfy_root.mkdir()
            (custom_nodes / "ComfyUI-Trellis2").mkdir(parents=True)
            with (
                patch.object(comfy_engine, "_comfy_python", return_value="/usr/bin/python3"),
                patch.object(comfy_engine, "_run", fake_run),
                patch.object(comfy_engine, "_module_available", lambda name, _p: name in available),
                patch.object(comfy_engine, "_ensure_cuda_build_tools"),
                patch.object(comfy_engine, "ensure_pixal3d_prebuilt_wheels", return_value=False),
                patch.object(comfy_engine, "_install_flash_attn_wheel", return_value=True),
                patch.object(
                    comfy_engine,
                    "_install_sparse_3d_prebuilt_wheels",
                    return_value=False,
                ),
            ):
                changed = comfy_engine.ensure_pixal3d_runtime(
                    comfy_root,
                    custom_nodes,
                    include_pixal3d=False,
                )
        self.assertFalse(changed)
        joined = " ".join(" ".join(cmd) for cmd in calls)
        self.assertNotIn("requirements.txt", joined)
        self.assertNotIn("moge", joined)
        self.assertNotIn("DRTK", joined)
        self.assertNotIn("flash-attn", joined)

    def test_prepare_runtime_symlinks_microsoft_and_facebook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comfy_root = root / "ComfyUI"
            workspace = root / "workspace"
            storage = root / "storage"
            comfy_root.mkdir()
            (comfy_root / "main.py").write_text("#\n", encoding="utf-8")
            comfy_engine.prepare_runtime(comfy_root, workspace, storage)
            for name in ("microsoft", "facebook"):
                link = comfy_root / "models" / name
                self.assertTrue(link.is_symlink(), name)
                self.assertEqual(link.resolve(), (storage / name).resolve())


if __name__ == "__main__":
    unittest.main()
