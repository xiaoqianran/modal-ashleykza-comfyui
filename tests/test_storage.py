import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import comfy_engine
from recipes import MODEL_DIRS, ModelAsset
from storage import (
    DEFAULT_STORAGE_ROOT,
    DEFAULT_STORAGE_VOLUME,
    ensure_storage_layout,
    extra_model_paths_yaml,
    legacy_model_path,
    resolve_model_file,
    storage_model_path,
)


class StorageLayoutTests(unittest.TestCase):
    def test_volume_paths_match_comfyui_model_categories(self):
        root = Path("/mnt/comfy-storage")
        self.assertEqual(DEFAULT_STORAGE_ROOT, root)
        self.assertEqual(DEFAULT_STORAGE_VOLUME, "comfyui-ashleykza-models")
        self.assertEqual(
            storage_model_path(root, "vae", "ae.safetensors"),
            root / "vae" / "ae.safetensors",
        )
        self.assertEqual(
            storage_model_path(root, "text_encoders", "qwen_3_4b.safetensors"),
            root / "text_encoders" / "qwen_3_4b.safetensors",
        )
        self.assertEqual(
            storage_model_path(root, "diffusion_models", "z_image_bf16.safetensors"),
            root / "diffusion_models" / "z_image_bf16.safetensors",
        )

    def test_rejects_unsafe_filenames(self):
        with self.assertRaises(ValueError):
            storage_model_path("/mnt/comfy-storage", "vae", "../escape.safetensors")
        with self.assertRaises(ValueError):
            storage_model_path("/mnt/comfy-storage", "not-a-category", "model.safetensors")

    def test_prefers_storage_then_legacy_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "storage"
            workspace = root / "workspace"
            ensure_storage_layout(storage)
            primary = storage / "vae" / "ae.safetensors"
            legacy = legacy_model_path(workspace, "vae", "ae.safetensors")
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_bytes(b"old")
            self.assertEqual(
                resolve_model_file(
                    storage_root=storage,
                    workspace=workspace,
                    category="vae",
                    filename="ae.safetensors",
                ),
                legacy,
            )
            primary.write_bytes(b"new")
            self.assertEqual(
                resolve_model_file(
                    storage_root=storage,
                    workspace=workspace,
                    category="vae",
                    filename="ae.safetensors",
                ),
                primary,
            )

    def test_extra_model_paths_maps_volume_dirs_one_to_one(self):
        yaml = extra_model_paths_yaml(
            storage_root="/mnt/comfy-storage",
            workspace="/workspace",
        )
        self.assertIn("modal_storage:", yaml)
        self.assertIn("base_path: /mnt/comfy-storage", yaml)
        self.assertIn("is_default: true", yaml)
        self.assertIn("base_path: /workspace", yaml)
        self.assertIn("custom_nodes: custom_nodes/", yaml)
        for name in MODEL_DIRS:
            self.assertIn(f"    {name}: {name}/", yaml)
            self.assertIn(f"    {name}: models/{name}/", yaml)


class HydrateStorageTests(unittest.TestCase):
    def test_hydrate_writes_comfyui_shaped_storage_tree(self):
        lock = {
            "schema": 1,
            "custom_nodes": [],
            "unresolved": [],
            "workflow": {"name": "demo.json", "sha256": "abc"},
            "models": [
                {
                    "category": "vae",
                    "filename": "ae.safetensors",
                    "url": "https://example.com/ae.safetensors",
                    "sha256": None,
                    "source": "test",
                },
                {
                    "category": "text_encoders",
                    "filename": "clip.safetensors",
                    "url": "https://example.com/clip.safetensors",
                    "sha256": None,
                    "source": "test",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "storage"
            workspace = root / "workspace"

            def fake_download(asset, target_dir, lock_entry=None):
                target = target_dir / comfy_engine.asset_filename(asset)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"model")
                return {"url": asset.url, "path": str(target), "size": 5}

            with patch.object(comfy_engine, "download_asset", fake_download):
                result = comfy_engine.sync_workflow_models(
                    lock,
                    workspace,
                    storage_root=storage,
                    workers=2,
                    workflow_source="examples/demo.json",
                    lock_source="examples/demo.lock.json",
                )

            vae = storage / "vae" / "ae.safetensors"
            clip = storage / "text_encoders" / "clip.safetensors"
            state = (storage / ".state" / "comfy.lock.json").read_text(encoding="utf-8")
            launch = comfy_engine.load_launch_state(storage)
            verified = comfy_engine.verify_workflow_models(
                lock,
                workspace,
                storage_root=storage,
            )
            yaml_dir = root / "ComfyUI"
            yaml_dir.mkdir(parents=True, exist_ok=True)
            yaml_path = comfy_engine.write_extra_model_paths(
                yaml_dir,
                workspace,
                storage,
            )
            self.assertTrue(vae.is_file())
            self.assertTrue(clip.is_file())
            self.assertEqual(result["downloaded"], 2)
            self.assertEqual(result["storage_root"], str(storage))
            self.assertIn("vae/ae.safetensors", state)
            self.assertEqual(verified["verified"], 2)
            self.assertIn("base_path: " + str(storage), yaml_path.read_text(encoding="utf-8"))
            self.assertEqual(launch["mode"], "workflow")
            self.assertEqual(launch["workflow"], "examples/demo.json")
            self.assertTrue(launch["install_lock_nodes"])
            self.assertEqual(launch["workflow_lock"]["workflow"]["name"], "demo.json")
            self.assertTrue((storage / ".state" / "workflow.lock.json").is_file())

    def test_hydrate_promotes_legacy_workspace_models(self):
        lock = {
            "schema": 1,
            "custom_nodes": [],
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
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "storage"
            workspace = root / "workspace"
            legacy = workspace / "models" / "vae" / "ae.safetensors"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_bytes(b"legacy-bytes")

            def fail_download(*_args, **_kwargs):
                raise AssertionError("should not download when legacy file exists")

            with patch.object(comfy_engine, "download_asset", wraps=comfy_engine.download_asset):
                with patch.object(comfy_engine, "_download_with_aria2", fail_download):
                    with patch.object(comfy_engine, "_parse_hf_url", return_value=None):
                        result = comfy_engine.sync_workflow_models(
                            lock,
                            workspace,
                            storage_root=storage,
                            workers=1,
                        )

            promoted = storage / "vae" / "ae.safetensors"
            self.assertTrue(promoted.is_file())
            self.assertEqual(promoted.read_bytes(), b"legacy-bytes")
            self.assertEqual(result["promoted"], 1)
            self.assertEqual(result["downloaded"], 0)

    def test_gpu_preflight_accepts_storage_and_rejects_missing(self):
        lock = {
            "schema": 1,
            "custom_nodes": [],
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
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "storage"
            workspace = root / "workspace"
            with self.assertRaisesRegex(RuntimeError, "hydrate"):
                comfy_engine.verify_workflow_models(
                    lock,
                    workspace,
                    storage_root=storage,
                )
            target = storage / "vae" / "ae.safetensors"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"model")
            verified = comfy_engine.verify_workflow_models(
                lock,
                workspace,
                storage_root=storage,
            )
        self.assertEqual(verified["verified"], 1)

    def test_profile_hydrate_uses_storage_root(self):
        asset = ModelAsset(url="https://example.com/model.safetensors", filename="model.safetensors")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = root / "storage"
            workspace = root / "workspace"

            def fake_download(model_asset, target_dir, lock_entry=None):
                target = target_dir / comfy_engine.asset_filename(model_asset)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"model")
                return {"url": model_asset.url, "path": str(target), "size": 5}

            with (
                patch.dict(
                    comfy_engine.MODEL_PACKS,
                    {"demo-pack": {"vae": (asset,)}},
                    clear=False,
                ),
                patch.object(
                    comfy_engine,
                    "get_profile",
                    return_value=type(
                        "P",
                        (),
                        {"model_packs": ("demo-pack",), "node_packs": (), "comfy_args": ()},
                    )(),
                ),
                patch.object(comfy_engine, "download_asset", fake_download),
            ):
                result = comfy_engine.sync_profile_models(
                    "demo",
                    workspace,
                    storage_root=storage,
                    workers=1,
                )

            self.assertTrue((storage / "vae" / "model.safetensors").is_file())
            self.assertEqual(result["downloaded"], 1)
            launch = comfy_engine.load_launch_state(storage)
            self.assertEqual(launch["mode"], "profile")
            self.assertEqual(launch["profile"], "demo")
            self.assertFalse(launch["install_lock_nodes"])
            self.assertIsNone(launch["workflow_lock"])
            self.assertFalse((storage / ".state" / "workflow.lock.json").exists())


class WaitReadyTests(unittest.TestCase):
    def test_wait_comfyui_ready_accepts_system_stats(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            comfy_engine.wait_comfyui_ready(port=server.server_address[1], timeout=5)
        finally:
            server.shutdown()
            server.server_close()


class OutputManifestTests(unittest.TestCase):
    def test_output_manifest_tracks_files_under_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "output"
            nested = root / "sub"
            nested.mkdir(parents=True)
            (root / "clip.mp4").write_bytes(b"abcd")
            (nested / "note.txt").write_text("ok", encoding="utf-8")
            manifest = comfy_engine.output_manifest(root)
            names = [name for name, _mtime, _size in manifest]
            self.assertEqual(names, ["clip.mp4", "sub/note.txt"])
            sizes = {name: size for name, _mtime, size in manifest}
            self.assertEqual(sizes["clip.mp4"], 4)


if __name__ == "__main__":
    unittest.main()
