import ast
import unittest
from pathlib import Path

from shipped_modules import (
    GPU_PYTHON_SOURCES,
    HYDRATE_PYTHON_SOURCES,
    windows_modules,
)

ROOT = Path(__file__).resolve().parents[1]


def _add_local_python_source_names(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "add_local_python_source":
            names: list[str] = []
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    names.append(arg.value)
                elif isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name):
                    if arg.value.id == "GPU_PYTHON_SOURCES":
                        return GPU_PYTHON_SOURCES
                    if arg.value.id == "HYDRATE_PYTHON_SOURCES":
                        return HYDRATE_PYTHON_SOURCES
            if names:
                return tuple(names)
    raise AssertionError(f"no add_local_python_source in {path}")


class ShippedModulesTests(unittest.TestCase):
    def test_every_source_file_exists(self):
        for name in (*GPU_PYTHON_SOURCES, *HYDRATE_PYTHON_SOURCES):
            self.assertTrue((ROOT / f"{name}.py").is_file(), name)
        for name in windows_modules():
            self.assertTrue((ROOT / name).is_file(), name)

    def test_hydrate_is_gpu_without_base_nodes(self):
        self.assertEqual(
            HYDRATE_PYTHON_SOURCES,
            tuple(name for name in GPU_PYTHON_SOURCES if name != "base_nodes"),
        )
        self.assertIn("runtime_hooks", GPU_PYTHON_SOURCES)
        self.assertIn("shipped_modules", GPU_PYTHON_SOURCES)
        self.assertIn("asset_sync", GPU_PYTHON_SOURCES)
        self.assertIn("engine_util", GPU_PYTHON_SOURCES)
        self.assertIn("node_install", GPU_PYTHON_SOURCES)

    def test_modal_images_star_the_shared_tuples(self):
        self.assertEqual(
            _add_local_python_source_names(ROOT / "comfyui_modal.py"),
            GPU_PYTHON_SOURCES,
        )
        self.assertEqual(
            _add_local_python_source_names(ROOT / "hydrate_modal.py"),
            HYDRATE_PYTHON_SOURCES,
        )

    def test_windows_modules_cover_gpu_sources_and_studio_entrypoints(self):
        bundled = set(windows_modules())
        for name in GPU_PYTHON_SOURCES:
            self.assertIn(f"{name}.py", bundled, name)
        self.assertIn("workflow_queue.py", bundled)
        self.assertIn("comfyui_modal.py", bundled)
        self.assertIn("hydrate_modal.py", bundled)


if __name__ == "__main__":
    unittest.main()
