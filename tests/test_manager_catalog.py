import json
import tempfile
import unittest
from pathlib import Path

from manager_catalog import (
    ManagerCatalog,
    classify_probe_nodes,
    enrich_lock,
    prepare_probe_lock,
    resolve_with_manager,
)
from workflow_resolver import (
    WorkflowResolutionError,
    dump_workflow_lock,
    resolve_workflow,
    workflow_file_sha256,
)


def _catalog() -> ManagerCatalog:
    return ManagerCatalog(
        extension_map={
            "https://github.com/kijai/ComfyUI-KJNodes": [
                ["KJNode", "SomethingElse", "SharedName"],
                {"title_aux": "KJNodes"},
            ],
            "https://github.com/other/ComfyUI-KJNodes": [
                ["SharedName"],
                {"title_aux": "fork"},
            ],
            "https://gist.githubusercontent.com/someone/abc/raw/file.py": [
                ["GistOnly"],
                {"title_aux": "gist"},
            ],
        },
        model_list={
            "models": [
                {
                    "name": "Style LoRA",
                    "type": "lora",
                    "save_path": "default",
                    "filename": "style.safetensors",
                    "url": "https://huggingface.co/example/lora/resolve/main/style.safetensors",
                },
                {
                    "name": "Unknown folder",
                    "type": "weird",
                    "save_path": "face_restore",
                    "filename": "restore.pth",
                    "url": "https://huggingface.co/example/restore/resolve/main/restore.pth",
                },
            ]
        },
        custom_node_list={
            "custom_nodes": [
                {
                    "id": "comfyui-kjnodes",
                    "files": ["https://github.com/kijai/ComfyUI-KJNodes"],
                }
            ]
        },
    )


class ManagerCatalogTests(unittest.TestCase):
    def test_binds_manager_lora_and_github_node(self):
        workflow = {
            "nodes": [
                {
                    "id": 1,
                    "type": "LoraLoader",
                    "widgets_values": ["style.safetensors"],
                    "properties": {"cnr_id": "comfy-core"},
                },
                {
                    "id": 2,
                    "type": "KJNode",
                    "widgets_values": [],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wf.json"
            path.write_text(json.dumps(workflow), encoding="utf-8")
            lock = resolve_workflow(path)
            self.assertTrue(lock["unresolved"])
            self.assertEqual(lock["custom_nodes"], [])
            filled = enrich_lock(lock, workflow, _catalog())
        self.assertEqual(filled["unresolved"], [])
        self.assertEqual(filled["models"][0]["filename"], "style.safetensors")
        self.assertEqual(filled["models"][0]["category"], "loras")
        self.assertEqual(filled["models"][0]["source"], "comfyui-manager")
        self.assertEqual(filled["custom_nodes"][0]["id"], "comfyui-kjnodes")
        self.assertEqual(
            filled["custom_nodes"][0]["url"],
            "https://github.com/kijai/ComfyUI-KJNodes",
        )

    def test_does_not_guess_when_node_type_maps_to_two_repos(self):
        workflow = {"nodes": [{"id": 1, "type": "SharedName", "widgets_values": []}]}
        lock = {
            "schema": 1,
            "workflow": {"name": "x.json", "sha256": "a" * 64},
            "models": [],
            "custom_nodes": [],
            "unresolved": [],
            "warnings": [],
        }
        filled = enrich_lock(lock, workflow, _catalog())
        self.assertEqual(filled["custom_nodes"], [])
        self.assertTrue(
            any(item.get("code") == "manager_node_conflict" for item in filled["warnings"])
        )

    def test_unknown_manager_folder_stays_unresolved_with_url(self):
        workflow = {
            "nodes": [
                {
                    "id": 1,
                    "type": "RestoreLoader",
                    "widgets_values": ["restore.pth"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wf.json"
            path.write_text(json.dumps(workflow), encoding="utf-8")
            lock = resolve_workflow(path)
            filled = enrich_lock(lock, workflow, _catalog())
        self.assertEqual(filled["models"], [])
        self.assertEqual(filled["unresolved"][0]["filename"], "restore.pth")
        self.assertEqual(filled["unresolved"][0]["reason"], "missing_category")
        self.assertIn("huggingface.co", filled["unresolved"][0]["url"])

    def test_resolve_with_manager_uses_loaded_catalog(self):
        workflow = {
            "nodes": [
                {
                    "id": 1,
                    "type": "LoraLoader",
                    "widgets_values": ["style.safetensors"],
                    "properties": {"cnr_id": "comfy-core"},
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wf.json"
            path.write_text(json.dumps(workflow), encoding="utf-8")
            lock = resolve_with_manager(path, _catalog())
        self.assertEqual(lock["manager"]["models_bound"], 1)

    def test_prepare_probe_lock_keeps_curated_file(self):
        workflow = {
            "nodes": [
                {
                    "id": 1,
                    "type": "LoraLoader",
                    "widgets_values": ["style.safetensors"],
                    "properties": {"cnr_id": "comfy-core"},
                },
                {"id": 2, "type": "KJNode", "widgets_values": []},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wf.json"
            lock_path = Path(directory) / "wf.lock.json"
            path.write_text(json.dumps(workflow), encoding="utf-8")
            curated = {
                "schema": 1,
                "workflow": {"name": "wf.json", "sha256": workflow_file_sha256(path)},
                "models": [
                    {
                        "category": "loras",
                        "filename": "style.safetensors",
                        "url": "https://huggingface.co/example/lora/resolve/main/style.safetensors",
                        "sha256": None,
                    }
                ],
                "custom_nodes": [],
                "unresolved": [],
                "warnings": [],
            }
            dump_workflow_lock(curated, lock_path)
            filled, origin = prepare_probe_lock(path, lock_path, _catalog())
        self.assertEqual(origin, "curated")
        self.assertEqual(filled["custom_nodes"], [])

    def test_prepare_probe_lock_writes_manager_lock(self):
        workflow = {
            "nodes": [
                {
                    "id": 1,
                    "type": "LoraLoader",
                    "widgets_values": ["style.safetensors"],
                    "properties": {"cnr_id": "comfy-core"},
                },
                {"id": 2, "type": "KJNode", "widgets_values": []},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wf.json"
            lock_path = Path(directory) / "wf.lock.json"
            path.write_text(json.dumps(workflow), encoding="utf-8")
            filled, origin = prepare_probe_lock(path, lock_path, _catalog())
            on_disk = json.loads(lock_path.read_text(encoding="utf-8"))
        self.assertEqual(origin, "manager")
        self.assertEqual(filled["custom_nodes"][0]["id"], "comfyui-kjnodes")
        self.assertEqual(on_disk["custom_nodes"][0]["id"], "comfyui-kjnodes")

    def test_prepare_probe_lock_refuses_to_clobber_curated_with_unresolved(self):
        workflow = {
            "nodes": [
                {
                    "id": 1,
                    "type": "RestoreLoader",
                    "widgets_values": ["restore.pth"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wf.json"
            lock_path = Path(directory) / "wf.lock.json"
            path.write_text(json.dumps(workflow), encoding="utf-8")
            curated = {
                "schema": 1,
                "workflow": {"name": "wf.json", "sha256": "a" * 64},
                "models": [
                    {
                        "category": "loras",
                        "filename": "style.safetensors",
                        "url": "https://huggingface.co/example/lora/resolve/main/style.safetensors",
                        "sha256": None,
                    }
                ],
                "custom_nodes": [],
                "unresolved": [],
                "warnings": [],
            }
            dump_workflow_lock(curated, lock_path)
            with self.assertRaises(WorkflowResolutionError):
                prepare_probe_lock(path, lock_path, _catalog())
            on_disk = json.loads(lock_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["models"][0]["filename"], "style.safetensors")

    def test_classify_probe_nodes_splits_locked_types(self):
        report = classify_probe_nodes(
            ["KJNode", "Trellis2LoadModel"],
            [{"id": "comfyui-kjnodes", "node_types": ["KJNode"]}],
        )
        self.assertEqual(report["missing_nodes_in_lock"], ["KJNode"])
        self.assertEqual(report["missing_nodes_unmapped"], ["Trellis2LoadModel"])


if __name__ == "__main__":
    unittest.main()
