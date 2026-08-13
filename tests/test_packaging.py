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

    def test_missing_python_exits_nonzero(self):
        launcher = _load("windows_launcher")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with patch.object(launcher, "bundle_root", return_value=base):
                self.assertEqual(launcher.main([]), 1)


class WindowsBundleTests(unittest.TestCase):
    def test_copy_app_includes_modal_sources(self):
        build = _load("build_windows")
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "app"
            build.copy_app(app)
            for name in build.MODULES:
                self.assertTrue((app / name).is_file(), name)
            self.assertTrue((app / "catalog" / "z-image.json").is_file())
            self.assertTrue((app / "studio" / "server.py").is_file())
            self.assertTrue((app / "examples" / "z-image-base.json").is_file())
            self.assertTrue((app / "examples" / "krea2-turbo-t2i.json").is_file())
            self.assertTrue((app / "README.txt").is_file())
            self.assertNotIn(".env", {path.name for path in app.iterdir()})


if __name__ == "__main__":
    unittest.main()
