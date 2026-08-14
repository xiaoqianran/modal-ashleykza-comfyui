import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import comfy_engine
import sam3d_runtime


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


class Sam3dLockGateTests(unittest.TestCase):
    def test_lock_id_matches_github_and_cnr_names(self):
        self.assertTrue(sam3d_runtime._lock_has_sam3d([{"id": "ComfyUI-SAM3DObjects"}]))
        self.assertTrue(sam3d_runtime._lock_has_sam3d([{"id": "comfyui-sam3dobjects"}]))
        self.assertFalse(sam3d_runtime._lock_has_sam3d([{"id": "ComfyUI-Trellis2"}]))
        self.assertFalse(sam3d_runtime._lock_has_sam3d([]))


def _fake_pixi(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"#!/bin/sh\n")
    path.chmod(0o755)
    return path


def _volume_comfy_env(workspace: Path, version: str = sam3d_runtime.COMFY_ENV_VERSION) -> Path:
    site = workspace / ".python" / "node-reqs"
    worker = site / "comfy_env" / "isolation" / "workers" / "subprocess.py"
    worker.parent.mkdir(parents=True, exist_ok=True)
    if not worker.is_file():
        worker.write_text(
            "                msg = self._transport.recv(timeout=60)\n"
            "        stdout=subprocess.DEVNULL,\n",
            encoding="utf-8",
        )
    meta = site / f"comfy_env-{version}.dist-info" / "METADATA"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(f"Name: comfy-env\nVersion: {version}\n", encoding="utf-8")
    return worker


def _ready_pixi_python(workspace: Path) -> Path:
    env_python = (
        workspace
        / ".python"
        / "comfy-env"
        / ".pixi"
        / "envs"
        / "sam3dobjects-nodes"
        / "bin"
        / "python"
    )
    env_python.parent.mkdir(parents=True, exist_ok=True)
    env_python.write_text("", encoding="utf-8")
    return env_python


def _ready_pixi_python_v04(workspace: Path) -> Path:
    env_python = (
        workspace
        / ".python"
        / "comfy-env"
        / "envs"
        / "sam3dobjects-nodes"
        / ".pixi"
        / "envs"
        / "default"
        / "bin"
        / "python"
    )
    env_python.parent.mkdir(parents=True, exist_ok=True)
    env_python.write_text("", encoding="utf-8")
    return env_python


class Sam3dRuntimeTests(unittest.TestCase):
    def test_apply_comfy_env_root_exports_volume_path(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop(sam3d_runtime.COMFY_ENV_ROOT_VAR, None)
                root = sam3d_runtime.apply_comfy_env_root(workspace)
                self.assertEqual(root, workspace / ".python" / "comfy-env")
                self.assertTrue(root.is_dir())
                self.assertEqual(os.environ[sam3d_runtime.COMFY_ENV_ROOT_VAR], str(root))

    def test_ensure_pixi_cli_copies_home_binary_onto_volume_and_relinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            home_bin = _fake_pixi(root / "home" / ".pixi" / "bin" / "pixi")
            with (
                patch.dict(os.environ, {"PATH": os.environ.get("PATH", "")}, clear=False),
                patch.object(sam3d_runtime, "home_pixi_bin", return_value=home_bin),
                patch.object(sam3d_runtime, "_download_pixi") as download,
            ):
                changed = sam3d_runtime.ensure_pixi_cli(workspace)
                volume = sam3d_runtime.volume_pixi_bin(workspace)
                self.assertIn(str(volume.parent), os.environ.get("PATH", "").split(os.pathsep))
            self.assertTrue(changed)
            self.assertTrue(volume.is_file())
            self.assertTrue(home_bin.is_symlink())
            self.assertEqual(home_bin.resolve(), volume.resolve())
            download.assert_not_called()

    def test_ensure_pixi_cli_downloads_when_volume_and_home_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            home_bin = root / "home" / ".pixi" / "bin" / "pixi"

            def fake_download(dest: Path) -> None:
                _fake_pixi(dest)

            with (
                patch.dict(os.environ, {"PATH": os.environ.get("PATH", "")}, clear=False),
                patch.object(sam3d_runtime, "home_pixi_bin", return_value=home_bin),
                patch.object(sam3d_runtime, "_download_pixi", side_effect=fake_download),
            ):
                changed = sam3d_runtime.ensure_pixi_cli(workspace)
            volume = sam3d_runtime.volume_pixi_bin(workspace)
            self.assertTrue(changed)
            self.assertTrue(volume.is_file())
            self.assertTrue(home_bin.is_symlink())
            self.assertEqual(home_bin.resolve(), volume.resolve())

    def test_ensure_pixi_cli_is_idempotent_when_volume_already_has_pixi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            volume = _fake_pixi(sam3d_runtime.volume_pixi_bin(workspace))
            home_bin = root / "home" / ".pixi" / "bin" / "pixi"
            with (
                patch.dict(os.environ, {"PATH": os.environ.get("PATH", "")}, clear=False),
                patch.object(sam3d_runtime, "home_pixi_bin", return_value=home_bin),
                patch.object(sam3d_runtime, "_download_pixi") as download,
            ):
                first = sam3d_runtime.ensure_pixi_cli(workspace)
                second = sam3d_runtime.ensure_pixi_cli(workspace)
            self.assertFalse(first)
            self.assertFalse(second)
            download.assert_not_called()
            self.assertTrue(home_bin.is_symlink())
            self.assertEqual(home_bin.resolve(), volume.resolve())

    def test_skips_when_node_dir_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            changed = sam3d_runtime.ensure_sam3d_runtime(
                root / "ComfyUI",
                root / "custom_nodes",
                workspace=root / "workspace",
            )
        self.assertFalse(changed)

    def test_skips_install_when_pixi_python_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            custom = root / "custom_nodes" / "ComfyUI-SAM3DObjects"
            custom.mkdir(parents=True)
            (custom / "install.py").write_text("raise SystemExit('nope')\n", encoding="utf-8")
            _ready_pixi_python(workspace)
            _volume_comfy_env(workspace)
            _fake_pixi(sam3d_runtime.volume_pixi_bin(workspace))
            home_bin = root / "home" / ".pixi" / "bin" / "pixi"
            calls: list[list[str]] = []

            def fake_run(cmd, **_kwargs):
                calls.append(cmd)

            with (
                patch.object(comfy_engine, "_run", fake_run),
                patch.object(sam3d_runtime, "home_pixi_bin", return_value=home_bin),
                patch.object(sam3d_runtime, "_download_pixi") as download,
            ):
                changed = sam3d_runtime.ensure_sam3d_runtime(
                    root / "ComfyUI",
                    root / "custom_nodes",
                    workspace=workspace,
                )
            self.assertFalse(changed)
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                calls[0][0],
                str(
                    sam3d_runtime.comfy_env_root(workspace)
                    / ".pixi"
                    / "envs"
                    / "sam3dobjects-nodes"
                    / "bin"
                    / "python"
                ),
            )
            download.assert_not_called()
            self.assertTrue(home_bin.is_symlink())

    def test_returns_true_when_pixi_cli_is_new_even_if_env_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            custom = root / "custom_nodes" / "ComfyUI-SAM3DObjects"
            custom.mkdir(parents=True)
            (custom / "install.py").write_text("raise SystemExit('nope')\n", encoding="utf-8")
            _ready_pixi_python(workspace)
            _volume_comfy_env(workspace)
            home_bin = root / "home" / ".pixi" / "bin" / "pixi"

            def fake_download(dest: Path) -> None:
                _fake_pixi(dest)

            with (
                patch.object(comfy_engine, "_run") as run,
                patch.object(sam3d_runtime, "home_pixi_bin", return_value=home_bin),
                patch.object(sam3d_runtime, "_download_pixi", side_effect=fake_download),
            ):
                changed = sam3d_runtime.ensure_sam3d_runtime(
                    root / "ComfyUI",
                    root / "custom_nodes",
                    workspace=workspace,
                )
            self.assertTrue(changed)
            self.assertTrue(sam3d_runtime.volume_pixi_bin(workspace).is_file())
            self.assertEqual(run.call_count, 1)
            self.assertTrue(any("sam3d-python-ok" in str(part) for part in run.call_args[0][0]))

    def test_patch_comfy_env_isolation_freezes_pixi_and_raises_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            comfy = Path(directory) / "ComfyUI"
            site = (
                comfy
                / "venv"
                / "lib"
                / "python3.12"
                / "site-packages"
                / "comfy_env"
                / "isolation"
                / "workers"
            )
            site.mkdir(parents=True)
            (site / "_ipc_shared.py").write_text(
                "SOCKET_ACCEPT_TIMEOUT = 60  # seconds to wait for worker to connect\n",
                encoding="utf-8",
            )
            (site / "subprocess.py").write_text(
                "is_pixi = '.pixi' in str(self.python)\n"
                'cmd = [\n    PIXI, "run", "--as-is",\n    "--manifest-path", str(manifest),\n]\n'
                "                msg = self._transport.recv(timeout=60)\n"
                "                if not msg:\n"
                '                    raise RuntimeError(f"{self.name}: Worker failed to send ready signal")\n'
                "        stdout=subprocess.DEVNULL,\n",
                encoding="utf-8",
            )
            (site.parent / "wrap.py").write_text(
                '        matches = glob.glob(str(env_dir / "lib/python*/site-packages"))\n'
                "        sp = Path(matches[0]) if matches else None\n",
                encoding="utf-8",
            )
            workspace = Path(directory) / "workspace"
            volume_worker = _volume_comfy_env(workspace)
            volume_worker.write_text(
                "                msg = self._transport.recv(timeout=60)\n"
                "        stdout=subprocess.DEVNULL,\n",
                encoding="utf-8",
            )
            self.assertTrue(sam3d_runtime.patch_comfy_env_isolation(comfy, workspace=workspace))
            self.assertFalse(sam3d_runtime.patch_comfy_env_isolation(comfy, workspace=workspace))
            ipc = (site / "_ipc_shared.py").read_text(encoding="utf-8")
            worker = (site / "subprocess.py").read_text(encoding="utf-8")
            wrap = (site.parent / "wrap.py").read_text(encoding="utf-8")
            self.assertIn("SOCKET_ACCEPT_TIMEOUT = 600", ipc)
            self.assertIn("is_pixi = False", worker)
            self.assertIn('PIXI, "run", "--as-is", "--frozen",', worker)
            self.assertIn("recv(timeout=600)", worker)
            self.assertNotIn("recv(timeout=60)", worker)
            self.assertIn(sam3d_runtime.WORKER_LOG, worker)
            self.assertNotIn("stdout=subprocess.DEVNULL", worker)
            self.assertIn("matches.sort", wrap)
            volume_worker = volume_worker.read_text(encoding="utf-8")
            self.assertIn("recv(timeout=600)", volume_worker)
            self.assertFalse(
                sam3d_runtime._ensure_volume_comfy_env(workspace, "python3")
            )

    def test_patch_comfy_env_isolation_raises_when_source_is_not_the_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            comfy = Path(directory) / "ComfyUI"
            site = (
                comfy
                / "venv"
                / "lib"
                / "python3.12"
                / "site-packages"
                / "comfy_env"
                / "isolation"
                / "workers"
            )
            site.mkdir(parents=True)
            (site / "subprocess.py").write_text(
                "# comfy-env 0.4 worker — no 0.3.89 ready recv\n",
                encoding="utf-8",
            )
            with self.assertRaises(sam3d_runtime._ce_contract.ComfyEnvContractError):
                sam3d_runtime.patch_comfy_env_isolation(comfy)

    def test_bridges_v04_layout_so_v03_wrap_can_see_env(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            custom = root / "custom_nodes" / "ComfyUI-SAM3DObjects"
            custom.mkdir(parents=True)
            (custom / "install.py").write_text("raise SystemExit('nope')\n", encoding="utf-8")
            _ready_pixi_python_v04(workspace)
            _volume_comfy_env(workspace)
            _fake_pixi(sam3d_runtime.volume_pixi_bin(workspace))
            home_bin = root / "home" / ".pixi" / "bin" / "pixi"
            calls: list[list[str]] = []

            def fake_run(cmd, **_kwargs):
                calls.append(cmd)

            with (
                patch.object(comfy_engine, "_run", fake_run),
                patch.object(sam3d_runtime, "home_pixi_bin", return_value=home_bin),
                patch.object(sam3d_runtime, "_download_pixi") as download,
            ):
                changed = sam3d_runtime.ensure_sam3d_runtime(
                    root / "ComfyUI",
                    root / "custom_nodes",
                    workspace=workspace,
                )
            self.assertTrue(changed)
            bridged = (
                sam3d_runtime.comfy_env_root(workspace)
                / ".pixi"
                / "envs"
                / "sam3dobjects-nodes"
                / "bin"
                / "python"
            )
            self.assertTrue(bridged.is_file())
            self.assertEqual(calls[0][0], str(bridged))
            download.assert_not_called()

    def test_ensure_volume_comfy_env_reinstalls_unpinned_or_04(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            _volume_comfy_env(workspace, version="0.4.18")
            calls: list[list[str]] = []

            def fake_run(cmd, **_kwargs):
                calls.append(cmd)
                _volume_comfy_env(workspace)

            with patch.object(comfy_engine, "_run", fake_run):
                changed = sam3d_runtime._ensure_volume_comfy_env(workspace, "python3")
            self.assertTrue(changed)
            self.assertEqual(len(calls), 1)
            self.assertIn(sam3d_runtime.COMFY_ENV_PIN, calls[0])
            self.assertEqual(
                sam3d_runtime._installed_comfy_env_version(
                    workspace / ".python" / "node-reqs"
                ),
                sam3d_runtime.COMFY_ENV_VERSION,
            )

    def test_warm_pixi_env_runs_isolated_python(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            python = _ready_pixi_python(workspace)
            calls: list[dict] = []

            def fake_run(cmd, **kwargs):
                calls.append({"cmd": cmd, "cwd": kwargs.get("cwd")})

            with (
                patch.dict(os.environ, {"PATH": os.environ.get("PATH", "")}, clear=False),
                patch.object(comfy_engine, "_run", fake_run),
            ):
                sam3d_runtime.warm_pixi_env(workspace)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["cmd"][0], str(python))
            self.assertTrue(any("sam3d-python-ok" in str(part) for part in calls[0]["cmd"]))

    def test_strips_geometrypack_and_runs_install_py(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            custom = root / "custom_nodes" / "ComfyUI-SAM3DObjects"
            custom.mkdir(parents=True)
            (custom / "install.py").write_text("print('install')\n", encoding="utf-8")
            (custom / "comfy-env-root.toml").write_text(
                '[node_reqs]\nComfyUI-GeometryPack = "PozzettiAndrea/ComfyUI-GeometryPack"\n',
                encoding="utf-8",
            )
            _volume_comfy_env(workspace)
            calls: list[dict] = []
            home_bin = root / "home" / ".pixi" / "bin" / "pixi"

            def fake_run(cmd, **kwargs):
                calls.append({"cmd": cmd, "cwd": kwargs.get("cwd"), "env": kwargs.get("env")})
                _ready_pixi_python(workspace)

            def fake_download(dest: Path) -> None:
                _fake_pixi(dest)

            with (
                patch.object(comfy_engine, "_comfy_python", return_value="python3"),
                patch.object(comfy_engine, "_run", fake_run),
                patch.object(sam3d_runtime, "home_pixi_bin", return_value=home_bin),
                patch.object(sam3d_runtime, "_download_pixi", side_effect=fake_download),
            ):
                changed = sam3d_runtime.ensure_sam3d_runtime(
                    root / "ComfyUI",
                    root / "custom_nodes",
                    workspace=workspace,
                )
            toml = (custom / "comfy-env-root.toml").read_text(encoding="utf-8")
        self.assertTrue(changed)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["cmd"][0], "python3")
        self.assertTrue(str(calls[0]["cmd"][1]).endswith("install.py"))
        self.assertEqual(calls[0]["cwd"], str(custom))
        self.assertEqual(
            calls[0]["env"][sam3d_runtime.COMFY_ENV_ROOT_VAR],
            str(workspace / ".python" / "comfy-env"),
        )
        self.assertTrue(any("sam3d-python-ok" in str(part) for part in calls[1]["cmd"]))
        self.assertNotIn("ComfyUI-GeometryPack", toml)


class Sam3dLaunchOrderTests(unittest.TestCase):
    def test_runs_sam3d_runtime_after_git_clone_without_sparse_wheels(self):
        order: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "storage"
            workspace = root / "workspace"
            comfy_root = root / "ComfyUI"
            comfy_root.mkdir()
            (comfy_root / "main.py").write_text("#\n", encoding="utf-8")
            target = storage / "sam3dobjects" / "pipeline.yaml"
            target.parent.mkdir(parents=True)
            target.write_text("pipeline: {}\n", encoding="utf-8")
            lock = _lock()
            lock["custom_nodes"] = [
                {
                    "id": "ComfyUI-SAM3DObjects",
                    "version": "main",
                    "url": "https://github.com/PozzettiAndrea/ComfyUI-SAM3DObjects.git",
                }
            ]
            lock["models"] = [
                {
                    "category": "sam3dobjects",
                    "filename": "pipeline.yaml",
                    "url": "https://example.com/pipeline.yaml",
                    "sha256": None,
                    "source": "test",
                }
            ]
            comfy_engine.persist_launch_state(
                storage,
                mode="workflow",
                workflow="sam3d.json",
                workflow_lock=lock,
            )

            def installer(*_args, **_kwargs):
                order.append("cnr")
                return ["ComfyUI-SAM3DObjects"]

            with (
                patch.dict(os.environ, {}, clear=False),
                patch.object(
                    comfy_engine,
                    "ensure_pixal3d_prebuilt_wheels",
                    side_effect=AssertionError("SAM 3D must not pull sparse-3d wheels"),
                ),
                patch.object(
                    comfy_engine,
                    "ensure_pixal3d_runtime",
                    side_effect=AssertionError("SAM 3D must not pull sparse-3d runtime"),
                ),
                patch.object(
                    comfy_engine,
                    "ensure_sam3d_runtime",
                    side_effect=lambda *_a, **_k: order.append("sam3d") or True,
                ),
            ):
                os.environ.pop(sam3d_runtime.COMFY_ENV_ROOT_VAR, None)
                _process, _fingerprint, newly = comfy_engine.apply_volume_launch(
                    storage_root=storage,
                    workspace=workspace,
                    comfy_root=comfy_root,
                    default_profile="base",
                    default_install_lock_nodes=True,
                    start_fn=lambda **_kwargs: DummyProcess(),
                    wait_fn=lambda **_kwargs: None,
                    install_nodes=installer,
                )
                self.assertEqual(
                    os.environ.get(sam3d_runtime.COMFY_ENV_ROOT_VAR),
                    str(workspace / ".python" / "comfy-env"),
                )
        self.assertEqual(order, ["cnr", "sam3d"])
        self.assertIn("ComfyUI-SAM3DObjects", newly)
        self.assertIn(sam3d_runtime.COMFY_ENV_SITE_MARK, newly)
        self.assertNotIn(comfy_engine.SPARSE_3D_SITE_MARK, newly)


if __name__ == "__main__":
    unittest.main()
