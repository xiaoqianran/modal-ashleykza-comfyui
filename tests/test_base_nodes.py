import json
import tempfile
import unittest
from pathlib import Path

import base_nodes


class BaseNodesTests(unittest.TestCase):
    def test_base_snapshot_is_complete(self):
        self.assertEqual(base_nodes.BASE_NODE_COUNT, 130)
        self.assertEqual(len(set(base_nodes.BASE_NODE_NAMES)), 130)
        self.assertEqual(len(base_nodes.BASE_NODE_SOURCES), 130)
        self.assertEqual(len(base_nodes.BASE_NODE_REPOS), 129)
        self.assertTrue(base_nodes.BASE_NODES_IMAGE.startswith("docker.cnb.cool/"))
        self.assertIn("ComfyUI-WanVideoWrapper", base_nodes.BASE_NODE_NAMES)
        self.assertIn("ComfyUI-KJNodes", base_nodes.BASE_NODE_NAMES)
        self.assertNotIn("ComfyUI-Manager", base_nodes.BASE_NODE_NAMES)
        self.assertIn("comfyui-manager", base_nodes.BASE_NODE_NAMES)
        self.assertIsNone(base_nodes.BASE_NODE_REPOS.get("comfyui-manager"))
        self.assertTrue(
            base_nodes.BASE_NODE_REPOS["ComfyUI-WanVideoWrapper"].startswith("https://github.com/")
        )
        self.assertTrue(
            all(
                url.startswith("https://github.com/") and url.endswith(".git")
                for url in base_nodes.BASE_NODE_REPOS.values()
            )
        )

    def test_clone_uses_unpinned_github_head(self):
        source = Path(base_nodes.__file__).read_text(encoding="utf-8")
        self.assertIn('["git", "clone", "--depth=1", url, str(dest)]', source)
        self.assertNotIn("--branch", source)
        self.assertNotIn("--commit", source)

    def test_base_build_clones_github_and_installs_requirements_sequentially(self):
        self.assertFalse(hasattr(base_nodes, "build_base_nodes_command"))
        commands = base_nodes.build_base_nodes_commands()
        joined = "\n".join(commands)
        self.assertNotIn("sparse-checkout", joined)
        self.assertNotIn("git init", joined)
        self.assertNotIn("cnb.cool/SKDZSS90/ComfyUI-yi_dian_tong.git", joined)
        self.assertIn("GITHUB_TOKEN", joined)
        self.assertIn("GIT_ASKPASS", joined)
        self.assertIn("uv pip install", joined)
        self.assertIn("--no-cache -r", joined)
        self.assertIn("custom_nodes/*/requirements.txt", joined)
        self.assertIn("comfyui-manager==4.2.2", joined)
        self.assertIn("/usr/local/bin/uv pip install --python", joined)
        self.assertNotIn("-m pip", joined)
        self.assertNotIn("node uv-sync", joined)
        self.assertNotIn("node install", joined)

    def test_base_build_commands_are_modal_dockerfile_safe(self):
        commands = base_nodes.build_base_nodes_commands()
        self.assertTrue(commands)
        for command in commands:
            self.assertNotIn("\n", command)
            self.assertNotIn("<<'", command)
            self.assertNotIn('<<"', command)
            self.assertNotIn("python3 -c ", command)
            self.assertNotIn("python -c ", command)

        joined = "\n".join(commands)
        self.assertIn(base_nodes.INSTALLER_REMOTE_PATH, joined)
        self.assertIn(f"/ComfyUI/venv/bin/python3 {base_nodes.INSTALLER_REMOTE_PATH}", joined)
        self.assertIn("--comfy-root", joined)

    def test_install_base_nodes_copies_wanted_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src_root = root / "src" / "custom_nodes"
            dst_root = root / "ComfyUI"
            for name in base_nodes.BASE_NODE_NAMES:
                node_dir = src_root / name
                node_dir.mkdir(parents=True)
                (node_dir / "marker.txt").write_text(name, encoding="utf-8")
                if name == "ComfyUI-KJNodes":
                    (node_dir / "git_backup").mkdir()
                    (node_dir / "git_backup" / "config").write_text("gitdir", encoding="utf-8")

            for manager_name in ("comfyui-manager", "ComfyUI-Manager"):
                manager = src_root / manager_name
                manager.mkdir(parents=True, exist_ok=True)
                (manager / "extra.txt").write_text("remove-me", encoding="utf-8")

            manifest_path = root / "comfy-base-nodes.json"
            base_nodes.install_base_nodes(
                comfy_root=str(dst_root),
                source_custom_nodes=str(src_root),
                manifest_path=str(manifest_path),
            )

            custom_nodes = dst_root / "custom_nodes"
            self.assertTrue((custom_nodes / "ComfyUI-WanVideoWrapper" / "marker.txt").read_text())
            self.assertEqual(
                (custom_nodes / "ComfyUI-KJNodes" / ".git" / "config").read_text(),
                "gitdir",
            )
            self.assertFalse((custom_nodes / "comfyui-manager").exists())
            self.assertFalse((custom_nodes / "ComfyUI-Manager").exists())

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["count"], 130)
            self.assertEqual(manifest["cloned"], 129)
            self.assertEqual(manifest["nodes"], list(base_nodes.BASE_NODE_NAMES))
            self.assertEqual(manifest["relaxed_pins"], [])

    def test_relax_drops_upper_bounds_and_exact_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            brush = root / "comfyui-brushnet"
            brush.mkdir()
            (brush / "requirements.txt").write_text(
                "diffusers>=0.29.0\naccelerate>=0.29.0,<0.32.0\npeft>=0.7.0\n",
                encoding="utf-8",
            )
            strings = root / "comfyui-stringsandthings"
            strings.mkdir()
            (strings / "requirements.txt").write_text("Pillow==10.3.0\n", encoding="utf-8")

            patched = base_nodes._relax_unsatisfiable_pins(root)
            self.assertEqual(
                patched,
                [
                    "comfyui-brushnet/requirements.txt",
                    "comfyui-stringsandthings/requirements.txt",
                ],
            )
            self.assertEqual(
                (brush / "requirements.txt").read_text(encoding="utf-8"),
                "diffusers>=0.29.0\naccelerate>=0.29.0\npeft>=0.7.0\n",
            )
            self.assertEqual(
                (strings / "requirements.txt").read_text(encoding="utf-8"),
                "Pillow>=10.3.0\n",
            )

    def test_relax_drops_packages_with_unsatisfiable_transitive_deps(self):
        text = "torch\ndescript-audiotools>=0.7.2\nprotobuf>=4.25.5\n"
        relaxed = base_nodes._relax_requirement_text(text)
        self.assertNotIn("descript-audiotools", relaxed)
        self.assertNotIn("torch", relaxed.split())
        self.assertIn("protobuf>=4.25.5", relaxed)

    def test_github_token_handling_happens_before_xtrace(self):
        command = base_nodes.build_base_nodes_commands()[0]
        self.assertLess(command.index("set -eu"), command.index("GITHUB_TOKEN"))
        self.assertLess(command.index("GITHUB_TOKEN"), command.index("set -x"))


if __name__ == "__main__":
    unittest.main()
