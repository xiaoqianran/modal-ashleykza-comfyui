import unittest

import benchmarks
from catalog import list_catalogs, load_catalog


class ModelListTests(unittest.TestCase):
    def test_overlay_covers_every_catalog_and_nothing_else(self):
        overlay = benchmarks.load_overlay()
        catalog_ids = [item["id"] for item in list_catalogs()]
        overlay_ids = [item["id"] for item in overlay["models"]]
        self.assertEqual(set(overlay_ids), set(catalog_ids))
        self.assertEqual(len(overlay_ids), len(set(overlay_ids)))

    def test_merged_rows_use_catalog_gpu_and_forbid_t4(self):
        for row in benchmarks.merged_models():
            catalog = load_catalog(row["id"])
            self.assertEqual(row["title"], catalog["title"], row["id"])
            self.assertEqual(row["kind"], catalog["kind"], row["id"])
            self.assertEqual(row["gpu"], catalog["gpu"], row["id"])
            self.assertNotEqual(row["gpu"], "T4", row["id"])
            self.assertNotIn("T4", catalog.get("gpu_choices") or [])
            smoke = row["overlay"].get("smoke") or {}
            self.assertNotEqual(smoke.get("gpu"), "T4", row["id"])
            self.assertIn(smoke.get("status"), benchmarks.SMOKE_STATUSES, row["id"])

    def test_recorded_smoke_has_seconds_and_gpu(self):
        for row in benchmarks.merged_models():
            smoke = row["overlay"].get("smoke") or {}
            if smoke.get("status") != "recorded":
                continue
            self.assertIsInstance(smoke.get("seconds"), (int, float), row["id"])
            self.assertGreater(float(smoke["seconds"]), 0, row["id"])
            self.assertTrue(str(smoke.get("gpu") or "").strip(), row["id"])
            self.assertTrue(str(smoke.get("source") or "").strip(), row["id"])

    def test_docs_page_is_generated_and_lists_every_id(self):
        text = benchmarks.render_models_markdown()
        self.assertTrue(text.startswith(benchmarks.GENERATED_BANNER))
        self.assertEqual(benchmarks.DOCS_PATH.read_text(encoding="utf-8"), text)
        for item in list_catalogs():
            self.assertIn(f"`{item['id']}`", text, item["id"])
            self.assertIn(item["title"], text, item["id"])
        self.assertNotRegex(text, r"\*\*T4\*\*|`T4`|\| T4 \|")

    def test_shared_weight_ids_exist(self):
        ids = {item["id"] for item in list_catalogs()}
        for row in benchmarks.merged_models():
            for other in row["overlay"].get("shared_weights_with") or ():
                self.assertIn(other, ids, f"{row['id']} -> {other}")


if __name__ == "__main__":
    unittest.main()
