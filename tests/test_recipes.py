import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import comfy_engine
import recipes


class RecipeTests(unittest.TestCase):
    def test_profile_references_exist(self):
        for profile in recipes.PROFILES.values():
            self.assertTrue(all(name in recipes.MODEL_PACKS for name in profile.model_packs))
            self.assertTrue(all(name in recipes.NODE_PACKS for name in profile.node_packs))

    def test_model_asset_destinations_are_unique_within_profile(self):
        for profile_name, profile in recipes.PROFILES.items():
            destinations = set()
            for pack_name in profile.model_packs:
                for category, assets in recipes.MODEL_PACKS[pack_name].items():
                    for asset in assets:
                        key = (category, comfy_engine.asset_filename(asset))
                        self.assertNotIn(key, destinations, (profile_name, key))
                        destinations.add(key)

    def test_node_names_are_unique_after_pack_resolution(self):
        for profile in recipes.PROFILES.values():
            names = []
            for pack_name in profile.node_packs:
                names.extend(node.name for node in recipes.NODE_PACKS[pack_name])
            self.assertTrue(all(names))
            commands = comfy_engine.build_node_commands(list(profile.node_packs))
            self.assertEqual(len(commands), len(set(names)))

    def test_no_plaintext_notebook_credentials_migrated(self):
        repo_root = Path(__file__).resolve().parents[1]
        text = "\n".join(path.read_text(encoding="utf-8") for path in repo_root.glob("*.py"))
        self.assertNotIn("hf_oYUjy", text)
        self.assertNotIn("AIzaSyCzFHq3", text)
        self.assertNotIn("4a9bc19474b3f2a973bc376efc5543a1", text)

    def test_huggingface_download_prefers_hf_xet_path(self):
        asset = recipes.M(
            "https://huggingface.co/example/repo/resolve/main/model.safetensors"
        )
        calls = []

        def fake_hf(_asset, _target_dir, target):
            calls.append("hf")
            target.write_bytes(b"model")

        def fake_aria(*_args, **_kwargs):
            calls.append("aria")
            raise AssertionError("aria2 should not be first choice for Hugging Face")

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(comfy_engine, "_download_with_hf_cli", fake_hf),
                patch.object(comfy_engine, "_download_with_aria2", fake_aria),
            ):
                comfy_engine.download_asset(asset, Path(directory))
        self.assertEqual(calls, ["hf"])

    def test_generic_download_uses_aria2(self):
        asset = recipes.M("https://example.com/model.safetensors")
        calls = []

        def fake_aria(_asset, _target_dir, target):
            calls.append("aria")
            target.write_bytes(b"model")

        def fake_hf(*_args, **_kwargs):
            calls.append("hf")
            raise AssertionError("HF downloader should not be used for generic URLs")

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(comfy_engine, "_download_with_aria2", fake_aria),
                patch.object(comfy_engine, "_download_with_hf_cli", fake_hf),
            ):
                comfy_engine.download_asset(asset, Path(directory))
        self.assertEqual(calls, ["aria"])

    def test_nested_filename_downloads_to_its_parent_directory(self):
        asset = recipes.M(
            "https://example.com/model.safetensors",
            filename="vendor/model.safetensors",
        )
        commands = []

        def fake_run(cmd, **_kwargs):
            commands.append(cmd)
            output_dir = Path(cmd[cmd.index("-d") + 1])
            output_path = output_dir / cmd[cmd.index("-o") + 1]
            output_path.write_bytes(b"model")

        with tempfile.TemporaryDirectory() as directory:
            target_dir = Path(directory)
            with (
                patch.object(comfy_engine.shutil, "which", return_value="/usr/bin/aria2c"),
                patch.object(comfy_engine, "_run", fake_run),
            ):
                comfy_engine.download_asset(asset, target_dir)

            self.assertTrue((target_dir / "vendor/model.safetensors").is_file())
            self.assertEqual(commands[0][commands[0].index("-d") + 1], str(target_dir / "vendor"))

    def test_repeated_category_filename_does_not_nest_under_category_dir(self):
        asset = recipes.M(
            "https://example.com/model.safetensors",
            filename="vae/model.safetensors",
        )
        commands = []

        def fake_run(cmd, **_kwargs):
            commands.append(cmd)
            output_dir = Path(cmd[cmd.index("-d") + 1])
            output_path = output_dir / cmd[cmd.index("-o") + 1]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"model")

        with tempfile.TemporaryDirectory() as directory:
            target_dir = Path(directory) / "vae"
            target_dir.mkdir()
            with (
                patch.object(comfy_engine.shutil, "which", return_value="/usr/bin/aria2c"),
                patch.object(comfy_engine, "_run", fake_run),
            ):
                comfy_engine.download_asset(asset, target_dir)

            self.assertTrue((target_dir / "model.safetensors").is_file())
            self.assertFalse((target_dir / "vae" / "model.safetensors").exists())
            self.assertEqual(commands[0][commands[0].index("-d") + 1], str(target_dir))
            self.assertEqual(commands[0][commands[0].index("-o") + 1], "model.safetensors")

    def test_node_build_supports_github_token_without_embedding_value(self):
        commands = comfy_engine.build_node_commands(["qwen-image-extra"])
        joined = "\n".join(commands)
        self.assertIn("GITHUB_TOKEN", joined)
        self.assertIn("x-access-token", joined)
        self.assertNotIn("github_pat_", joined)
        self.assertIn('"$UV" pip install --python "$PY" --no-cache', joined)
        self.assertNotIn("-m pip", joined)

    def test_github_token_handling_happens_before_xtrace(self):
        command = comfy_engine.build_node_commands(["qwen-image-extra"])[0]
        self.assertLess(command.index("set -eu"), command.index("GITHUB_TOKEN"))
        self.assertLess(command.index("GITHUB_TOKEN"), command.index("set -x"))

    def test_civitai_token_is_redacted_from_command_logs(self):
        asset = recipes.M("https://civitai.com/api/download/models/123")
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            target_dir = Path(directory)
            with (
                patch.dict(os.environ, {"CIVITAI_TOKEN": "top-secret-token"}),
                patch.object(comfy_engine.shutil, "which", return_value="/usr/bin/aria2c"),
                patch.object(comfy_engine.subprocess, "run"),
                redirect_stdout(output),
            ):
                comfy_engine._download_with_aria2(
                    asset,
                    target_dir,
                    target_dir / "model.safetensors",
                )

        self.assertNotIn("top-secret-token", output.getvalue())
        self.assertIn("token=%2A%2A%2A", output.getvalue())

    def test_extra_nodes_do_not_duplicate_base_snapshot(self):
        import base_nodes

        base = {name.casefold() for name in base_nodes.BASE_NODE_NAMES}
        for pack_name, pack in recipes.NODE_PACKS.items():
            for node in pack:
                self.assertTrue(node.name)
                self.assertNotIn(node.name.casefold(), base, (pack_name, node.name))

    def test_wan_lean_profile_needs_no_extra_nodes(self):
        self.assertEqual(recipes.PROFILES["wan22"].node_packs, ())


if __name__ == "__main__":
    unittest.main()
