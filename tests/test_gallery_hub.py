"""Tests for the Hugging Face gallery hub (no network)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gallery_hub import bucket_for_kind, build_index, collection_dir, slug
from gallery_hub.build_pages import build_pages
from gallery_hub.report import report
from gallery_hub.stage import stage_collection

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class GalleryHubTests(unittest.TestCase):
    def test_kind_buckets(self):
        self.assertEqual(bucket_for_kind("t2i"), "image")
        self.assertEqual(bucket_for_kind("i2i"), "image")
        self.assertEqual(bucket_for_kind("t2v"), "video")
        self.assertEqual(bucket_for_kind("i2v"), "video")
        self.assertEqual(bucket_for_kind("i23d"), "mesh3d")
        with self.assertRaises(ValueError):
            bucket_for_kind("other")

    def test_slug_and_paths(self):
        self.assertEqual(slug("FLUX.2 Dev"), "flux.2-dev")
        path = collection_dir(Path("/tmp/hub"), "image", "flux2-dev", "campus-days")
        self.assertEqual(path.as_posix(), "/tmp/hub/image/flux2-dev/campus-days")

    def test_stage_and_pages_build(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            media = root / "in.png"
            media.write_bytes(TINY_PNG)
            staged = stage_collection(
                dest_root=root / "hub",
                recipe="flux2-dev",
                collection="campus-days",
                title="美好的校园时光",
                kind="t2i",
                summary="Shinkai look",
                items=[
                    {
                        "id": "001",
                        "title": "校门晨曦",
                        "prompt": "A school gate at dawn.",
                        "media_path": media,
                    }
                ],
            )
            sidecar = json.loads((staged / "001.json").read_text(encoding="utf-8"))
            self.assertEqual(sidecar["prompt"], "A school gate at dawn.")
            self.assertEqual(sidecar["media"], "001.png")
            self.assertTrue((staged / "001.png").is_file())
            index = build_index(root / "hub", repo="seachen/modal-comfyui-picture")
            self.assertEqual(index["item_count"], 1)
            self.assertEqual(index["collections"][0]["recipe"], "flux2-dev")

            gallery = root / "docs-gallery"
            generated = build_pages(
                src=root / "hub",
                docs_gallery=gallery,
                repo="seachen/modal-comfyui-picture",
            )
            text = generated.read_text(encoding="utf-8")
            self.assertIn("校门晨曦", text)
            self.assertIn("A school gate at dawn.", text)
            self.assertIn("gallery-grid", text)
            thumbs = list((gallery / "media").rglob("*.jpg")) + list((gallery / "media").rglob("*.png"))
            self.assertTrue(thumbs)

    def test_report_counts_and_refuses_empty_when_required(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            media = root / "in.png"
            media.write_bytes(TINY_PNG)
            stage_collection(
                dest_root=root / "hub",
                recipe="flux2-dev",
                collection="campus-days",
                title="美好的校园时光",
                kind="t2i",
                items=[
                    {
                        "id": "001",
                        "title": "校门晨曦",
                        "prompt": "A school gate at dawn.",
                        "media_path": media,
                    }
                ],
            )
            index = report(root / "hub", repo="seachen/modal-comfyui-picture")
            self.assertEqual(index["collection_count"], 1)
            self.assertEqual(index["item_count"], 1)
            with self.assertRaises(SystemExit):
                report(root / "empty", repo="seachen/modal-comfyui-picture", require_items=True)

    def test_pages_workflow_audits_hf_pull(self):
        text = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "docs.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("HF_GALLERY_REPO: seachen/modal-comfyui-picture", text)
        self.assertIn("python -m gallery_hub.pull", text)
        self.assertIn("python -m gallery_hub.report", text)
        self.assertIn("--require-items", text)
        self.assertIn("python -m gallery_hub.build_pages", text)
        self.assertIn("secrets.HF_TOKEN", text)


if __name__ == "__main__":
    unittest.main()
