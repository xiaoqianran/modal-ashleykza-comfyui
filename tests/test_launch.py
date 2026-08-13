import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import comfy_engine
import workflow_resolver


def _lock(name: str = "demo.json", sha: str = "abc") -> dict:
    return {
        "schema": 1,
        "custom_nodes": [{"id": "comfyui-kjnodes", "version": "1.0"}],
        "unresolved": [],
        "workflow": {"name": name, "sha256": sha},
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


class DummyProcess:
    def __init__(self):
        self.code = None
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.code = 0


class LaunchFingerprintTests(unittest.TestCase):
    def test_changes_when_custom_nodes_change(self):
        launch = {
            "profile": "base",
            "install_lock_nodes": True,
            "workflow_lock": _lock(),
        }
        first = comfy_engine.launch_fingerprint(
            launch, profile_name="base", install_lock_nodes=True
        )
        launch["workflow_lock"]["custom_nodes"] = []
        second = comfy_engine.launch_fingerprint(
            launch, profile_name="base", install_lock_nodes=True
        )
        self.assertNotEqual(first, second)


class ApplyVolumeLaunchTests(unittest.TestCase):
    def test_repairs_nested_models_before_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "storage"
            workspace = root / "workspace"
            comfy_root = root / "ComfyUI"
            comfy_root.mkdir()
            (comfy_root / "main.py").write_text("#\n", encoding="utf-8")
            nested = storage / "vae" / "vae" / "ae.safetensors"
            nested.parent.mkdir(parents=True)
            nested.write_bytes(b"model")
            lock = _lock()
            lock["custom_nodes"] = []
            comfy_engine.persist_launch_state(
                storage,
                mode="workflow",
                workflow="demo.json",
                lock_source="demo.lock.json",
                workflow_lock=lock,
            )
            started = []

            def start_fn(**_kwargs):
                started.append(True)
                return DummyProcess()

            process, fingerprint, newly = comfy_engine.apply_volume_launch(
                storage_root=storage,
                workspace=workspace,
                comfy_root=comfy_root,
                default_profile="base",
                default_install_lock_nodes=True,
                start_fn=start_fn,
                wait_fn=lambda **_kwargs: None,
                install_nodes=lambda *_args, **_kwargs: [],
            )
            self.assertTrue(started)
            self.assertTrue((storage / "vae" / "ae.safetensors").is_file())
            self.assertFalse((storage / "vae" / "vae").exists())
            self.assertTrue(fingerprint)
            self.assertEqual(newly, [])
            self.assertIs(process.poll(), None)

    def test_reuses_process_when_fingerprint_matches(self):
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
            lock["custom_nodes"] = []
            comfy_engine.persist_launch_state(
                storage,
                mode="workflow",
                workflow="demo.json",
                workflow_lock=lock,
            )
            existing = DummyProcess()
            fingerprint = comfy_engine.launch_fingerprint(
                comfy_engine.load_launch_state(storage),
                profile_name="base",
                install_lock_nodes=True,
            )
            start_fn = Mock(side_effect=AssertionError("should not restart"))
            process, next_fingerprint, newly = comfy_engine.apply_volume_launch(
                storage_root=storage,
                workspace=workspace,
                comfy_root=comfy_root,
                default_profile="base",
                default_install_lock_nodes=True,
                previous_fingerprint=fingerprint,
                process=existing,
                start_fn=start_fn,
                wait_fn=lambda **_kwargs: None,
                install_nodes=lambda *_args, **_kwargs: [],
            )
            self.assertIs(process, existing)
            self.assertEqual(next_fingerprint, fingerprint)
            self.assertEqual(newly, [])
            start_fn.assert_not_called()


class SelectWorkflowLockTests(unittest.TestCase):
    def test_reuses_matching_resolved_lock(self):
        workflow = {"nodes": [{"id": 1, "type": "Note", "widgets_values": []}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "wf.json"
            source.write_text(json.dumps(workflow), encoding="utf-8")
            sha = workflow_resolver.workflow_file_sha256(source)
            lock = {
                "schema": 1,
                "workflow": {"name": "wf.json", "sha256": sha},
                "models": [
                    {
                        "category": "vae",
                        "filename": "ae.safetensors",
                        "url": "https://example.com/ae.safetensors",
                        "sha256": None,
                        "source": "manual",
                    }
                ],
                "custom_nodes": [],
                "unresolved": [],
            }
            lock_path = root / "wf.lock.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            loaded, origin = workflow_resolver.select_workflow_lock(source, lock_path)
            self.assertEqual(origin, "reused")
            self.assertEqual(loaded["models"][0]["filename"], "ae.safetensors")

    def test_refuses_to_clobber_curated_lock_with_unresolved_resolve(self):
        workflow = {
            "nodes": [
                {
                    "id": 1,
                    "type": "VAELoader",
                    "widgets_values": ["mystery.safetensors"],
                    "properties": {"cnr_id": "comfy-core"},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "wf.json"
            source.write_text(json.dumps({"nodes": []}), encoding="utf-8")
            sha = workflow_resolver.workflow_file_sha256(source)
            lock = {
                "schema": 1,
                "workflow": {"name": "wf.json", "sha256": sha},
                "models": [
                    {
                        "category": "vae",
                        "filename": "ae.safetensors",
                        "url": "https://example.com/ae.safetensors",
                        "sha256": None,
                        "source": "manual",
                    }
                ],
                "custom_nodes": [],
                "unresolved": [],
            }
            lock_path = root / "wf.lock.json"
            lock_path.write_text(json.dumps(lock), encoding="utf-8")
            source.write_text(json.dumps(workflow), encoding="utf-8")
            with self.assertRaisesRegex(workflow_resolver.WorkflowResolutionError, "curated"):
                workflow_resolver.select_workflow_lock(source, lock_path)
            kept = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(kept["models"][0]["filename"], "ae.safetensors")


if __name__ == "__main__":
    unittest.main()
