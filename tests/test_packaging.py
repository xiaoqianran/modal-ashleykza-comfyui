import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    path = ROOT / "packaging" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class WindowsLauncherTests(unittest.TestCase):
    def test_layout_points_at_bundled_python_and_app(self):
        launcher = _load("windows_launcher")
        python, app = launcher.layout(Path("/bundle/Studio"))
        self.assertEqual(python, Path("/bundle/Studio/python/python.exe"))
        self.assertEqual(app, Path("/bundle/Studio/app"))

    def test_missing_payload_exits_nonzero(self):
        launcher = _load("windows_launcher")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with patch.object(launcher, "meipass", return_value=base):
                self.assertEqual(launcher.main([]), 1)

    def test_ensure_runtime_copies_once(self):
        launcher = _load("windows_launcher")
        with tempfile.TemporaryDirectory() as directory:
            src = Path(directory) / "src"
            dest = Path(directory) / "dest"
            python, app = launcher.layout(src)
            python.parent.mkdir(parents=True)
            python.write_text("", encoding="utf-8")
            (app / "studio").mkdir(parents=True)
            (src / launcher.STAMP_NAME).write_text("abc\n", encoding="utf-8")
            self.assertTrue(launcher.ensure_runtime(src, dest))
            self.assertTrue((dest / "python" / "python.exe").is_file())
            self.assertTrue((dest / "app" / "studio").is_dir())
            self.assertEqual(launcher.stamp_of(dest), "abc")
            self.assertFalse(launcher.ensure_runtime(src, dest))


class WindowsBundleTests(unittest.TestCase):
    def test_copy_app_includes_modal_sources(self):
        from catalog import list_catalogs, load_catalog

        build = _load("build_windows")
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "app"
            build.copy_app(app)
            for name in build.MODULES:
                self.assertTrue((app / name).is_file(), name)
            self.assertTrue((app / "catalog" / "gates.py").is_file())
            self.assertTrue((app / "studio" / "server.py").is_file())
            self.assertTrue((app / "studio" / "cost.py").is_file())
            self.assertTrue((app / "studio" / "trace.py").is_file())
            self.assertTrue((app / "benchmarks" / "models.json").is_file())
            self.assertFalse((app / "benchmarks.py").is_file())
            self.assertTrue((app / "README.txt").is_file())
            self.assertNotIn(".env", {path.name for path in app.iterdir()})
            for item in list_catalogs():
                catalog = load_catalog(item["id"])
                self.assertTrue((app / "catalog" / f"{item['id']}.json").is_file(), item["id"])
                self.assertTrue((app / catalog["workflow"]).is_file(), item["id"])
                self.assertTrue((app / catalog["lock"]).is_file(), item["id"])

    def test_write_stamp(self):
        build = _load("build_windows")
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory)
            with patch.dict("os.environ", {"GITHUB_SHA": "deadbeef"}, clear=False):
                path = build.write_stamp(payload)
            self.assertEqual(path.read_text(encoding="utf-8").strip(), "deadbeef")

    def test_modal_pip_spec_includes_api_proxy_support(self):
        build = _load("build_windows")
        self.assertEqual(build.MODAL_PIP_SPEC, "modal[api-proxy-support]")


if __name__ == "__main__":
    unittest.main()
