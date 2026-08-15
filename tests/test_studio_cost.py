import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shipped_modules import GPU_PYTHON_SOURCES
from studio import cost as studio_cost
from studio.server import _generate_batch

ROOT = Path(__file__).resolve().parents[1]


class GpuRateCardTests(unittest.TestCase):
    def test_l40s_and_pro6000_match_frozen_rate_card(self):
        self.assertEqual(studio_cost.PRICE_AS_OF, "2026-08-12")
        self.assertEqual(studio_cost.usd_per_second("L40S"), 0.000542)
        self.assertEqual(studio_cost.usd_per_second("RTX PRO 6000"), 0.000842)
        self.assertEqual(studio_cost.usd_for_seconds("L40S", 1), 0.000542)
        self.assertAlmostEqual(studio_cost.usd_for_seconds("L40S", 3600), 1.9512, places=4)

    def test_unknown_gpu_raises(self):
        with self.assertRaises(ValueError):
            studio_cost.usd_per_second("mystery-card")


class PredictTests(unittest.TestCase):
    def test_recorded_smoke_plus_one_scaledown(self):
        payload = studio_cost.predict(recipe="cosmos3-edge", gpu="L40S", count=1)
        self.assertEqual(payload["mode"], "recorded")
        self.assertEqual(payload["smoke_seconds"], 49.06)
        self.assertEqual(payload["scaledown_seconds"], 5)
        self.assertEqual(payload["jobs"], 1)
        self.assertEqual(payload["seconds"], 54.06)
        self.assertEqual(payload["usd"], round(54.06 * 0.000542, 6))
        self.assertIn("不含 Volume", payload["hint"])
        self.assertNotIn("T4", payload["hint"])

    def test_two_jobs_add_scaledown_once(self):
        payload = studio_cost.predict(recipe="cosmos3-edge", gpu="L40S", count=2)
        self.assertEqual(payload["job_seconds"], 98.12)
        self.assertEqual(payload["seconds"], 103.12)

    def test_pending_smoke_is_rate_only(self):
        payload = studio_cost.predict(recipe="z-image", gpu="L40S")
        self.assertEqual(payload["mode"], "rate_only")
        self.assertIsNone(payload["usd"])
        self.assertIsNone(payload["seconds"])
        self.assertIn("不编造", payload["hint"])
        self.assertGreater(payload["usd_per_hour"], 1.9)

    def test_selected_gpu_can_differ_from_smoke_gpu(self):
        payload = studio_cost.predict(recipe="cosmos3-edge", gpu="RTX-PRO-6000", count=1)
        self.assertEqual(payload["gpu"], "RTX-PRO-6000")
        self.assertEqual(payload["smoke_gpu"], "L40S")
        self.assertEqual(payload["usd"], round(54.06 * 0.000842, 6))
        self.assertIn("秒数来自 L40S", payload["hint"])

    def test_keep_gpu_omits_scaledown_from_total(self):
        payload = studio_cost.predict(
            recipe="cosmos3-edge", gpu="L40S", count=1, keep_gpu=True
        )
        self.assertEqual(payload["seconds"], 49.06)
        self.assertIn("占卡", payload["hint"])

    def test_missing_overlay_is_rate_only(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "models.json"
            with patch.object(studio_cost, "OVERLAY_PATH", missing):
                payload = studio_cost.predict(recipe="", gpu="L40S")
        self.assertEqual(payload["mode"], "rate_only")
        self.assertEqual(payload["scaledown_seconds"], 5)


class TraceTests(unittest.TestCase):
    def test_jsonl_strips_secrets_and_reads_recent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cost-trace.jsonl"
            first = studio_cost.record_event(
                {"kind": "generate", "recipe": "sam3d", "usd": 0.1, "HF_TOKEN": "hf_secret"},
                path=path,
            )
            studio_cost.record_event({"kind": "generate", "recipe": "pixal3d", "usd": 0.2}, path=path)
            self.assertNotIn("HF_TOKEN", first)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("hf_secret", text)
            self.assertNotIn("HF_TOKEN", text)
            events = studio_cost.recent_events(limit=1, path=path)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["recipe"], "pixal3d")


class CliTests(unittest.TestCase):
    def test_cli_prints_predict_json(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            code = studio_cost.main(["--recipe", "z-image", "--gpu", "L40S"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["mode"], "rate_only")
        self.assertEqual(payload["gpu"], "L40S")

    def test_cli_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cost-trace.jsonl"
            studio_cost.record_event({"kind": "generate", "recipe": "z-image"}, path=path)
            buf = io.StringIO()
            with patch.object(studio_cost, "TRACE_PATH", path), patch("sys.stdout", buf):
                code = studio_cost.main(["--trace"])
        self.assertEqual(code, 0)
        events = json.loads(buf.getvalue())
        self.assertEqual(events[0]["recipe"], "z-image")


class SidecarBoundaryTests(unittest.TestCase):
    def test_not_on_gpu_image(self):
        self.assertNotIn("studio.cost", GPU_PYTHON_SOURCES)
        self.assertNotIn("cost", GPU_PYTHON_SOURCES)
        for name in GPU_PYTHON_SOURCES:
            text = (ROOT / f"{name}.py").read_text(encoding="utf-8")
            self.assertNotIn("studio.cost", text, name)
            self.assertNotIn("from studio import cost", text, name)

    def test_generate_records_cost_without_breaking_stop(self):
        payload = {
            "prompts": ["a teapot"],
            "catalog": "cosmos3-edge",
            "gpu": "L40S",
        }
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "cost-trace.jsonl"
            with (
                patch(
                    "studio.server._run_generate_batch",
                    return_value={"ok": True, "count": 1, "catalog": "cosmos3-edge", "results": []},
                ),
                patch(
                    "studio.server.stop_gpu",
                    return_value={"stopped": True, "pid": None, "containers": []},
                ) as stop,
                patch.object(studio_cost, "TRACE_PATH", trace),
            ):
                result = _generate_batch("job-cost", payload)
            stop.assert_called_once()
            self.assertIn("cost", result)
            self.assertEqual(result["cost"]["kind"], "generate")
            self.assertEqual(result["cost"]["gpu"], "L40S")
            self.assertEqual(result["cost"]["jobs"], 1)
            self.assertFalse(result["cost"]["keep_gpu"])
            self.assertGreaterEqual(result["cost"]["billable_seconds"], result["cost"]["seconds"])
            logged = json.loads(trace.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(logged["recipe"], "cosmos3-edge")
            self.assertNotIn("token", json.dumps(logged).lower())


if __name__ == "__main__":
    unittest.main()
