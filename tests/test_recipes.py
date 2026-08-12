from pathlib import Path

import comfy_engine
import recipes


def test_profile_references_exist():
    for profile in recipes.PROFILES.values():
        assert all(name in recipes.MODEL_PACKS for name in profile.model_packs)
        assert all(name in recipes.NODE_PACKS for name in profile.node_packs)


def test_model_asset_destinations_are_unique_within_profile():
    for profile_name, profile in recipes.PROFILES.items():
        destinations = set()
        for pack_name in profile.model_packs:
            for category, assets in recipes.MODEL_PACKS[pack_name].items():
                for asset in assets:
                    key = (category, comfy_engine.asset_filename(asset))
                    assert key not in destinations, (profile_name, key)
                    destinations.add(key)


def test_node_names_are_unique_after_pack_resolution():
    for profile_name, profile in recipes.PROFILES.items():
        names = []
        for pack_name in profile.node_packs:
            names.extend(node.name for node in recipes.NODE_PACKS[pack_name])
        assert all(names)
        commands = comfy_engine.build_node_commands(list(profile.node_packs))
        assert len(commands) == len(set(names))


def test_no_plaintext_notebook_credentials_migrated():
    repo_root = Path(__file__).resolve().parents[1]
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in repo_root.glob("*.py")
    )
    assert "hf_oYUjy" not in text
    assert "AIzaSyCzFHq3" not in text
    assert "4a9bc19474b3f2a973bc376efc5543a1" not in text


def test_huggingface_download_prefers_hf_xet_path(tmp_path, monkeypatch):
    asset = recipes.M(
        "https://huggingface.co/example/repo/resolve/main/model.safetensors"
    )
    calls = []

    def fake_hf(asset, target_dir, target):
        calls.append("hf")
        target.write_bytes(b"model")

    def fake_aria(*args, **kwargs):
        calls.append("aria")
        raise AssertionError("aria2 should not be first choice for Hugging Face")

    monkeypatch.setattr(comfy_engine, "_download_with_hf_cli", fake_hf)
    monkeypatch.setattr(comfy_engine, "_download_with_aria2", fake_aria)

    comfy_engine.download_asset(asset, tmp_path)
    assert calls == ["hf"]


def test_generic_download_uses_aria2(tmp_path, monkeypatch):
    asset = recipes.M("https://example.com/model.safetensors")
    calls = []

    def fake_aria(asset, target_dir, target):
        calls.append("aria")
        target.write_bytes(b"model")

    def fake_hf(*args, **kwargs):
        calls.append("hf")
        raise AssertionError("HF downloader should not be used for generic URLs")

    monkeypatch.setattr(comfy_engine, "_download_with_aria2", fake_aria)
    monkeypatch.setattr(comfy_engine, "_download_with_hf_cli", fake_hf)

    comfy_engine.download_asset(asset, tmp_path)
    assert calls == ["aria"]


def test_node_build_supports_github_token_without_embedding_value():
    commands = comfy_engine.build_node_commands(["qwen-image"])
    joined = "\n".join(commands)
    assert "GITHUB_TOKEN" in joined
    assert "x-access-token" in joined
    assert "github_pat_" not in joined


def test_github_token_handling_happens_before_xtrace():
    command = comfy_engine.build_node_commands(["qwen-image"])[0]
    assert command.index("set -eu") < command.index("GITHUB_TOKEN") < command.index("set -x")
