import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

import comfy_engine
import workflow_resolver


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _workflow_png(workflow: dict) -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    text = b"workflow\0" + json.dumps(workflow).encode()
    pixels = zlib.compress(b"\x00\x00\x00\x00")
    return (
        workflow_resolver.PNG_SIGNATURE
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"tEXt", text)
        + _png_chunk(b"IDAT", pixels)
        + _png_chunk(b"IEND", b"")
    )


def _sample_workflow() -> dict:
    return {
        "nodes": [
            {
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "widgets_values": ["qwen/model.safetensors"],
                "properties": {
                    "cnr_id": "comfy-core",
                    "models": [
                        {
                            "name": "model.safetensors",
                            "url": "https://huggingface.co/example/repo/resolve/main/model.safetensors",
                            "hash": "a" * 64,
                            "hash_type": "SHA256",
                            "directory": "models/checkpoints/qwen",
                        }
                    ],
                },
            },
            {
                "id": 2,
                "type": "KJNode",
                "widgets_values": [],
                "properties": {"cnr_id": "comfyui-kjnodes", "ver": "1.2.3"},
            },
            {
                "id": 3,
                "type": "LoraLoader",
                "widgets_values": ["style.safetensors"],
                "properties": {"cnr_id": "comfy-core"},
            },
        ]
    }


class WorkflowResolverTests(unittest.TestCase):
    def test_resolves_declared_models_nodes_and_missing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.json"
            path.write_text(json.dumps(_sample_workflow()), encoding="utf-8")
            lock = workflow_resolver.resolve_workflow(path)

        self.assertEqual(lock["schema"], 1)
        self.assertEqual(lock["models"][0]["category"], "checkpoints")
        self.assertEqual(lock["models"][0]["filename"], "qwen/model.safetensors")
        self.assertEqual(lock["models"][0]["sha256"], "a" * 64)
        self.assertEqual(lock["custom_nodes"][0]["id"], "comfyui-kjnodes")
        self.assertEqual(lock["custom_nodes"][0]["version"], "1.2.3")
        self.assertEqual(lock["unresolved"][0]["category"], "loras")
        self.assertEqual(lock["unresolved"][0]["filename"], "style.safetensors")

    def test_reads_workflow_from_png_text_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.png"
            path.write_bytes(_workflow_png(_sample_workflow()))
            lock = workflow_resolver.resolve_workflow(path)
        self.assertEqual(lock["workflow"]["name"], "workflow.png")
        self.assertEqual(len(lock["models"]), 1)

    def test_writes_and_validates_lock_atomically(self):
        workflow = _sample_workflow()
        workflow["nodes"][2]["widgets_values"] = []
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "workflow.json"
            output = Path(directory) / "locks" / "workflow.lock.json"
            source.write_text(json.dumps(workflow), encoding="utf-8")
            workflow_resolver.write_workflow_lock(source, output)
            lock = workflow_resolver.load_workflow_lock(output, require_resolved=True)
        self.assertEqual(lock["unresolved"], [])

    def test_rejects_path_traversal_in_model_metadata(self):
        workflow = _sample_workflow()
        workflow["nodes"][0]["properties"]["models"][0]["name"] = "../../model.safetensors"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.json"
            path.write_text(json.dumps(workflow), encoding="utf-8")
            with self.assertRaises(workflow_resolver.WorkflowResolutionError):
                workflow_resolver.resolve_workflow(path)

    def test_rejects_non_http_model_url(self):
        workflow = _sample_workflow()
        workflow["nodes"][0]["properties"]["models"][0]["url"] = "file:///etc/passwd"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.json"
            path.write_text(json.dumps(workflow), encoding="utf-8")
            with self.assertRaises(workflow_resolver.WorkflowResolutionError):
                workflow_resolver.resolve_workflow(path)

    def test_rejects_tampered_lock_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.json"
            path.write_text(json.dumps(_sample_workflow()), encoding="utf-8")
            lock = workflow_resolver.resolve_workflow(path)
        lock["models"][0]["filename"] = "../../escape.safetensors"
        with self.assertRaises(workflow_resolver.WorkflowResolutionError):
            workflow_resolver.validate_workflow_lock(lock)

    def test_syncs_locked_models_into_workspace(self):
        workflow = _sample_workflow()
        workflow["nodes"][2]["widgets_values"] = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "workflow.json"
            source.write_text(json.dumps(workflow), encoding="utf-8")
            lock = workflow_resolver.resolve_workflow(source)

            def fake_download(asset, target_dir, lock_entry=None):
                target = target_dir / comfy_engine.asset_filename(asset)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"model")
                return {"url": asset.url, "path": str(target), "size": 5}

            with patch.object(comfy_engine, "download_asset", fake_download):
                result = comfy_engine.sync_workflow_models(lock, root / "workspace")

            target = root / "workspace/models/checkpoints/qwen/model.safetensors"
            state = json.loads((root / "workspace/state/comfy.lock.json").read_text())
            target_exists = target.is_file()

        self.assertTrue(target_exists)
        self.assertEqual(result["synced"], 1)
        self.assertIn("models/checkpoints/qwen/model.safetensors", state["assets"])


if __name__ == "__main__":
    unittest.main()
