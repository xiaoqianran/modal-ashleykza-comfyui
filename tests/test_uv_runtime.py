import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import uv_runtime
from shipped_modules import GPU_PYTHON_SOURCES

CONTAINER_FILES = tuple(f"{name}.py" for name in GPU_PYTHON_SOURCES) + (
    "comfyui_modal.py",
    "hydrate_modal.py",
)


def _gzip_uv_tarball(directory: Path) -> bytes:
    root = directory / "uv-x86_64-unknown-linux-musl"
    root.mkdir(parents=True)
    (root / "uv").write_bytes(b"#!/bin/sh\n")
    (root / "uvx").write_bytes(b"#!/bin/sh\n")
    archive = directory / "uv.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(root, arcname=root.name)
    return archive.read_bytes()


class UvRuntimeTests(unittest.TestCase):
    def test_pip_install_cmd_targets_venv_python(self):
        cmd = uv_runtime.pip_install_cmd(
            "/ComfyUI/venv/bin/python",
            "-r",
            "requirements.txt",
            uv="/usr/local/bin/uv",
        )
        self.assertTrue(uv_runtime.is_uv_pip_cmd(cmd))
        self.assertEqual(
            cmd,
            [
                "/usr/local/bin/uv",
                "pip",
                "install",
                "--python",
                "/ComfyUI/venv/bin/python",
                "--no-cache",
                "-r",
                "requirements.txt",
            ],
        )

    def test_pip_install_cmd_keeps_target_for_volume_site(self):
        cmd = uv_runtime.pip_install_cmd(
            "python3",
            "--no-deps",
            "flex_gemm.whl",
            site_dir="/workspace/.python/sparse-3d",
            uv="uv",
        )
        self.assertIn("--target", cmd)
        self.assertIn("/workspace/.python/sparse-3d", cmd)
        self.assertTrue(uv_runtime.is_uv_pip_cmd(cmd))

    def test_uvx_cmd_is_the_pipx_replacement(self):
        self.assertEqual(uv_runtime.uvx_cmd("ruff", "check", uvx="/usr/local/bin/uvx"), [
            "/usr/local/bin/uvx",
            "ruff",
            "check",
        ])

    def test_image_bootstrap_downloads_musl_uv_without_pip(self):
        command = uv_runtime.image_install_uv_command()
        self.assertIn(uv_runtime.UV_LINUX_X64_URL, command)
        self.assertIn("/usr/local/bin/uv", command)
        self.assertIn("/usr/local/bin/uvx", command)
        self.assertIn("/ComfyUI/venv/bin/uv", command)
        self.assertNotIn("-m pip", command)
        self.assertNotIn("pip install", command)

    def test_image_uv_pip_and_uninstall_commands(self):
        install = uv_runtime.image_uv_pip_command(
            "/ComfyUI/venv/bin/python",
            "comfy-cli==1.16.0",
        )
        upgrade = uv_runtime.image_uv_pip_command(
            "/ComfyUI/venv/bin/python",
            "typing_extensions>=4.14",
            upgrade=True,
        )
        uninstall = uv_runtime.image_uv_uninstall_command(
            "/ComfyUI/venv/bin/python3",
            "pathlib",
            "pathlib2",
        )
        self.assertIn(
            "/usr/local/bin/uv pip install --python /ComfyUI/venv/bin/python --no-cache comfy-cli==1.16.0",
            install,
        )
        self.assertIn(" -U ", upgrade)
        self.assertIn(
            "/usr/local/bin/uv pip uninstall --python /ComfyUI/venv/bin/python3 -y pathlib pathlib2",
            uninstall,
        )
        self.assertNotIn("-m pip", install + upgrade + uninstall)

    def test_install_uv_tarball_copies_uv_and_uvx(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = _gzip_uv_tarball(root / "src")

            def fake_urlopen(_url, timeout=120):
                del timeout
                return io.BytesIO(payload)

            dest = root / "bin"
            with patch.object(uv_runtime.urllib.request, "urlopen", fake_urlopen):
                uv = uv_runtime.install_uv_tarball(dest, url="https://example.test/uv.tgz")
            self.assertEqual(uv, dest / "uv")
            self.assertTrue((dest / "uv").is_file())
            self.assertTrue((dest / "uvx").is_file())
            self.assertTrue((dest / "uv").stat().st_mode & 0o111)

    def test_container_python_does_not_call_pip_or_pipx(self):
        repo = Path(__file__).resolve().parents[1]
        for name in CONTAINER_FILES:
            text = (repo / name).read_text(encoding="utf-8")
            self.assertNotIn("-m pip", text, name)
            self.assertNotIn("pipx install", text, name)
            self.assertNotIn("pipx run", text, name)


if __name__ == "__main__":
    unittest.main()
