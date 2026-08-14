import json
import tempfile
import unittest
from pathlib import Path

import recipe_scaffold
from catalog.gates import TEST_GPU


def _workflow_with_url() -> dict:
    return {
        "nodes": [
            {
                "id": 1,
                "type": "CheckpointLoaderSimple",
                "widgets_values": ["demo.safetensors"],
                "properties": {
                    "cnr_id": "comfy-core",
                    "models": [
                        {
                            "name": "demo.safetensors",
                            "directory": "checkpoints",
                            "url": "https://huggingface.co/example/demo/resolve/main/demo.safetensors",
                        }
                    ],
                },
            }
        ]
    }


def _workflow_unresolved() -> dict:
    return {
        "nodes": [
            {
                "id": 1,
                "type": "LoraLoader",
                "widgets_values": ["orphan.safetensors"],
                "properties": {"cnr_id": "comfy-core"},
            }
        ]
    }


class RecipeScaffoldTests(unittest.TestCase):
    def test_draft_is_workflow_mode_on_l40s(self):
        payload = recipe_scaffold.build_catalog_draft(
            recipe_id="demo-t2i",
            title="Demo",
            kind="t2i",
            workflow="examples/demo.json",
            lock="examples/demo.lock.json",
        )
        self.assertEqual(payload["mode"], "workflow")
        self.assertEqual(payload["gpu"], TEST_GPU)
        self.assertEqual(payload["gpu_inference"], "RTX-PRO-6000")
        self.assertEqual(payload["params"][0]["bind"], "prompt")
        self.assertNotIn("graph", payload)

    def test_i23d_draft_is_image_only(self):
        payload = recipe_scaffold.build_catalog_draft(
            recipe_id="demo-3d",
            title="Demo 3D",
            kind="i23d",
            workflow="examples/demo.json",
            lock="examples/demo.lock.json",
        )
        self.assertEqual(payload["params"][0]["bind"], "image")
        self.assertTrue(payload["params"][0]["required"])

    def test_refuses_t4_and_ungated_pro6000(self):
        with self.assertRaisesRegex(ValueError, "forbidden"):
            recipe_scaffold.build_catalog_draft(
                recipe_id="demo-t2i",
                title="Demo",
                kind="t2i",
                workflow="examples/demo.json",
                lock="examples/demo.lock.json",
                gpu="T4",
            )
        with self.assertRaisesRegex(ValueError, "NON_L40S_DEFAULT_GPU_IDS"):
            recipe_scaffold.build_catalog_draft(
                recipe_id="demo-t2i",
                title="Demo",
                kind="t2i",
                workflow="examples/demo.json",
                lock="examples/demo.lock.json",
                gpu="RTX-PRO-6000",
            )

    def test_refuses_to_scaffold_graph_exceptions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "in.json"
            source.write_text(json.dumps(_workflow_with_url()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mode=graph"):
                recipe_scaffold.scaffold(
                    source,
                    recipe_id="z-image",
                    title="Nope",
                    kind="t2i",
                    root=root,
                )

    def test_write_copies_workflow_and_prints_unresolved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "examples").mkdir()
            (root / "catalog").mkdir()
            source = root / "incoming.json"
            source.write_text(json.dumps(_workflow_unresolved()), encoding="utf-8")
            result = recipe_scaffold.scaffold(
                source,
                recipe_id="orphan-lora",
                title="Orphan",
                kind="t2i",
                root=root,
                write=True,
            )
            self.assertTrue(result.wrote)
            self.assertFalse(result.resolved)
            self.assertTrue(result.catalog.is_file())
            self.assertTrue(result.lock.is_file())
            self.assertTrue(result.workflow.is_file())
            self.assertEqual(result.unresolved[0]["filename"], "orphan.safetensors")
            code = recipe_scaffold.main(
                [
                    str(source),
                    "--id",
                    "orphan-lora",
                    "--title",
                    "Orphan",
                    "--kind",
                    "t2i",
                    "--root",
                    str(root),
                ]
            )
            self.assertEqual(code, 2)

    def test_write_resolved_lock_and_overlay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            examples = root / "examples"
            examples.mkdir()
            (root / "catalog").mkdir()
            overlay = {
                "schema": 1,
                "updated": "2026-08-14",
                "environment": {},
                "models": [],
            }
            overlay_path = root / "benchmarks" / "models.json"
            overlay_path.parent.mkdir()
            overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
            source = examples / "demo-t2i.json"
            source.write_text(json.dumps(_workflow_with_url()), encoding="utf-8")
            result = recipe_scaffold.scaffold(
                source,
                recipe_id="demo-t2i",
                title="Demo",
                kind="t2i",
                root=root,
                write=True,
                write_overlay=True,
            )
            self.assertTrue(result.resolved)
            self.assertTrue(result.overlay_wrote)
            written = json.loads(overlay_path.read_text(encoding="utf-8"))
            self.assertEqual(written["models"][0]["id"], "demo-t2i")
            catalog = json.loads(result.catalog.read_text(encoding="utf-8"))
            self.assertEqual(catalog["workflow"], "examples/demo-t2i.json")
            self.assertEqual(catalog["mode"], "workflow")
