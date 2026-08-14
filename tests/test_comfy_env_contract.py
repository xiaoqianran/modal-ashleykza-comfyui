import tempfile
import unittest
from pathlib import Path

import comfy_engine
import comfy_env_contract as contract


def _write_pin(site: Path, version: str = contract.VERSION) -> Path:
    worker = site / "comfy_env" / "isolation" / "workers" / "subprocess.py"
    worker.parent.mkdir(parents=True, exist_ok=True)
    worker.write_text(
        f"{contract.READY_RECV_STOCK}\n{contract.STDOUT_STOCK}\n",
        encoding="utf-8",
    )
    meta = site / f"comfy_env-{version}.dist-info" / "METADATA"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(f"Name: comfy-env\nVersion: {version}\n", encoding="utf-8")
    return worker


def _touch_python(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


class ComfyEnvContractTests(unittest.TestCase):
    def test_pin_is_the_node_pack_version_not_latest(self):
        self.assertEqual(contract.VERSION, "0.3.89")
        self.assertEqual(contract.PIN, "comfy-env==0.3.89")
        self.assertEqual(contract.SKIP_PACKAGES, frozenset({"comfy-env"}))
        self.assertEqual(comfy_engine.NODE_REQS_SKIP_PACKAGES, contract.SKIP_PACKAGES)

    def test_installed_version_reads_dist_info(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            _write_pin(site, "0.4.18")
            _write_pin(site, "0.3.89")
            self.assertEqual(contract.installed_version(site), "0.4.18")

    def test_pin_satisfied_requires_worker_and_exact_version(self):
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty"
            empty.mkdir()
            self.assertFalse(contract.pin_satisfied(empty))
            floated = Path(directory) / "floated"
            _write_pin(floated, "0.4.18")
            self.assertFalse(contract.pin_satisfied(floated))
            pinned = Path(directory) / "pinned"
            _write_pin(pinned, contract.VERSION)
            self.assertTrue(contract.pin_satisfied(pinned))

    def test_assert_pinned_fails_on_float(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            _write_pin(site, "0.4.18")
            with self.assertRaises(contract.ComfyEnvContractError) as ctx:
                contract.assert_pinned(site)
            self.assertIn(contract.PIN, str(ctx.exception))

    def test_isolation_visible_is_only_the_v03_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v04 = _touch_python(
                root / "envs" / "sam3dobjects-nodes" / ".pixi" / "envs" / "default" / "bin" / "python"
            )
            self.assertFalse(contract.isolation_visible(root))
            self.assertTrue(contract.env_materialized(root))
            self.assertEqual(contract.isolation_python_bins(root), [v04])
            v03 = _touch_python(root / ".pixi" / "envs" / "sam3dobjects-nodes" / "bin" / "python")
            self.assertTrue(contract.isolation_visible(root))
            self.assertEqual(contract.isolation_python_bins(root), [v03])

    def test_bridge_makes_v04_workspace_visible_to_v03_wrap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            v04 = _touch_python(
                root / "envs" / "sam3dobjects-nodes" / ".pixi" / "envs" / "default" / "bin" / "python"
            )
            self.assertTrue(contract.ensure_v03_layout(root))
            self.assertFalse(contract.ensure_v03_layout(root))
            dest = root / ".pixi" / "envs" / "sam3dobjects-nodes"
            self.assertTrue(dest.is_symlink())
            self.assertTrue((dest / "bin" / "python").is_file())
            self.assertEqual((dest / "bin" / "python").resolve(), v04.resolve())
            contract.assert_isolation_visible(root)

    def test_assert_isolation_visible_fails_when_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(contract.ComfyEnvContractError):
                contract.assert_isolation_visible(directory)

    def test_assert_patchable_fails_when_ready_recv_is_gone(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            worker = _write_pin(site)
            worker.write_text("print('not 0.3.89')\n", encoding="utf-8")
            with self.assertRaises(contract.ComfyEnvContractError) as ctx:
                contract.assert_patchable(site)
            self.assertIn("ready recv", str(ctx.exception))

    def test_assert_patchable_accepts_already_patched_source(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            worker = _write_pin(site)
            worker.write_text(
                f"{contract.READY_RECV_OURS}\n{contract.STDOUT_OURS}\n",
                encoding="utf-8",
            )
            contract.assert_patchable(site)

    def test_assert_boot_requires_pin_and_v03_env(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with self.assertRaises(contract.ComfyEnvContractError):
                contract.assert_boot(workspace)
            _write_pin(contract.node_reqs_site(workspace))
            with self.assertRaises(contract.ComfyEnvContractError):
                contract.assert_boot(workspace)
            _touch_python(
                contract.volume_root(workspace)
                / ".pixi"
                / "envs"
                / "sam3dobjects-nodes"
                / "bin"
                / "python"
            )
            contract.assert_boot(workspace)


if __name__ == "__main__":
    unittest.main()
