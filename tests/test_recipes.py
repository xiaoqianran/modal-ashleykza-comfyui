import json
from pathlib import Path

import base_nodes
import comfy_engine
import recipes


def test_base_snapshot_is_pinned_and_complete():
    assert base_nodes.BASE_NODE_COUNT == 130
    assert len(set(base_nodes.BASE_NODE_NAMES)) == 130
    assert len(base_nodes.BASE_NODE_SOURCES) == 130
    assert len(base_nodes.BASE_NODE_REPOS) == 129
    assert base_nodes.BASE_NODES_IMAGE.startswith("docker.cnb.cool/")
    assert "ComfyUI-WanVideoWrapper" in base_nodes.BASE_NODE_NAMES
    assert "ComfyUI-KJNodes" in base_nodes.BASE_NODE_NAMES
    assert "ComfyUI-Manager" not in base_nodes.BASE_NODE_NAMES  # snapshot uses normalized lowercase
    assert "comfyui-manager" in base_nodes.BASE_NODE_NAMES
    assert base_nodes.BASE_NODE_REPOS.get("comfyui-manager") is None
    assert base_nodes.BASE_NODE_REPOS["ComfyUI-WanVideoWrapper"].startswith("https://github.com/")
    assert all(
        url.startswith("https://github.com/") and url.endswith(".git")
        for url in base_nodes.BASE_NODE_REPOS.values()
    )


def test_base_build_clones_github_and_runs_unified_dependency_sync():
    commands = base_nodes.build_base_nodes_commands()
    joined = "\n".join(commands)
    assert "sparse-checkout" not in joined
    assert "git init" not in joined
    assert "cnb.cool/SKDZSS90/ComfyUI-yi_dian_tong.git" not in joined
    assert "GITHUB_TOKEN" in joined
    assert "GIT_ASKPASS" in joined
    assert "node uv-sync" in joined
    assert "comfy-cli==1.12.0" in joined
    assert "comfyui-manager==4.2.2" in joined
    # nodes.md entries are directory names, not Registry IDs; do not feed them
    # directly to `comfy node install`.
    assert "node install" not in joined


def test_base_build_commands_are_modal_dockerfile_safe():
    """Modal wraps each run_commands entry into Dockerfile RUN; no heredoc / python -c."""
    commands = base_nodes.build_base_nodes_commands()
    assert commands, "expected at least one shell step"
    for command in commands:
        assert "\n" not in command, command
        assert "<<'" not in command
        assert '<<"' not in command
        assert "python3 -c " not in command
        assert "python -c " not in command

    joined = "\n".join(commands)
    assert base_nodes.INSTALLER_REMOTE_PATH in joined
    assert f"/ComfyUI/venv/bin/python3 {base_nodes.INSTALLER_REMOTE_PATH}" in joined
    assert "--comfy-root" in joined


def test_install_base_nodes_copies_wanted_and_writes_manifest(tmp_path):
    src_root = tmp_path / "src" / "custom_nodes"
    dst_root = tmp_path / "ComfyUI"
    for name in base_nodes.BASE_NODE_NAMES:
        node_dir = src_root / name
        node_dir.mkdir(parents=True)
        (node_dir / "marker.txt").write_text(name, encoding="utf-8")
        # Simulate upstream git_backup layout for one node.
        if name == "ComfyUI-KJNodes":
            (node_dir / "git_backup").mkdir()
            (node_dir / "git_backup" / "config").write_text("gitdir", encoding="utf-8")

    # Copied manager dirs must be removed after install.
    for manager_name in ("comfyui-manager", "ComfyUI-Manager"):
        manager = src_root / manager_name
        if not manager.exists():
            manager.mkdir(parents=True)
        (manager / "extra.txt").write_text("remove-me", encoding="utf-8")

    manifest_path = tmp_path / "comfy-base-nodes.json"
    base_nodes.install_base_nodes(
        comfy_root=str(dst_root),
        source_custom_nodes=str(src_root),
        manifest_path=str(manifest_path),
    )

    custom_nodes = dst_root / "custom_nodes"
    assert (custom_nodes / "ComfyUI-WanVideoWrapper" / "marker.txt").read_text(encoding="utf-8")
    assert (custom_nodes / "ComfyUI-KJNodes" / ".git" / "config").read_text(encoding="utf-8") == "gitdir"
    assert not (custom_nodes / "comfyui-manager").exists()
    assert not (custom_nodes / "ComfyUI-Manager").exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["count"] == 130
    assert manifest["cloned"] == 129
    assert manifest["image"] == base_nodes.BASE_NODES_IMAGE
    assert manifest["nodes"] == list(base_nodes.BASE_NODE_NAMES)
    assert len(manifest["repositories"]) == 129


def test_profile_references_exist():
    for profile in recipes.PROFILES.values():
        assert all(name in recipes.MODEL_PACKS for name in profile.model_packs)
        assert all(name in recipes.NODE_PACKS for name in profile.node_packs)


def test_model_categories_are_supported():
    for pack in recipes.MODEL_PACKS.values():
        assert set(pack).issubset(set(recipes.MODEL_DIRS))


def test_model_asset_destinations_are_unique_within_profile():
    for profile_name, profile in recipes.PROFILES.items():
        destinations = set()
        for pack_name in profile.model_packs:
            for category, assets in recipes.MODEL_PACKS[pack_name].items():
                for asset in assets:
                    key = (category, comfy_engine.asset_filename(asset))
                    assert key not in destinations, (profile_name, key)
                    destinations.add(key)


def test_extra_nodes_do_not_duplicate_base_snapshot():
    base = {name.casefold() for name in base_nodes.BASE_NODE_NAMES}
    for pack_name, pack in recipes.NODE_PACKS.items():
        for node in pack:
            assert node.name
            assert node.name.casefold() not in base, (pack_name, node.name)


def test_node_names_are_unique_after_pack_resolution():
    for profile_name, profile in recipes.PROFILES.items():
        names = []
        for pack_name in profile.node_packs:
            names.extend(node.name for node in recipes.NODE_PACKS[pack_name])
        assert all(names)
        commands = comfy_engine.build_node_commands(list(profile.node_packs))
        assert len(commands) == len(set(names)), profile_name


def test_wan_lean_profile_needs_no_extra_nodes():
    assert recipes.PROFILES["wan22"].node_packs == ()


def test_no_plaintext_notebook_credentials_migrated():
    repo_root = Path(__file__).resolve().parents[1]
    text = "\n".join(path.read_text(encoding="utf-8") for path in repo_root.glob("*.py"))
    assert "hf_oYUjy" not in text
    assert "AIzaSyCzFHq3" not in text
    assert "4a9bc19474b3f2a973bc376efc5543a1" not in text


def test_huggingface_download_prefers_hf_xet_path(tmp_path, monkeypatch):
    asset = recipes.M("https://huggingface.co/example/repo/resolve/main/model.safetensors")
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
    commands = comfy_engine.build_node_commands(["qwen-image-extra"])
    joined = "\n".join(commands)
    assert "GITHUB_TOKEN" in joined
    assert "x-access-token" in joined
    assert "github_pat_" not in joined


def test_github_token_handling_happens_before_xtrace():
    command = comfy_engine.build_node_commands(["qwen-image-extra"])[0]
    assert command.index("set -eu") < command.index("GITHUB_TOKEN") < command.index("set -x")


def test_base_clone_uses_github_token_before_xtrace():
    command = base_nodes.build_base_nodes_commands()[0]
    assert command.index("set -eu") < command.index("GITHUB_TOKEN") < command.index("set -x")
    assert "--source-custom-nodes" not in command


def test_install_base_nodes_clones_github_when_no_source_tree(tmp_path, monkeypatch):
    cloned: list[tuple[str, str]] = []

    def fake_clone(url: str, dest: Path) -> None:
        dest.mkdir(parents=True)
        (dest / "marker.txt").write_text(url, encoding="utf-8")
        cloned.append((dest.name, url))

    monkeypatch.setattr(base_nodes, "_clone_repo", fake_clone)

    dst_root = tmp_path / "ComfyUI"
    manifest_path = tmp_path / "comfy-base-nodes.json"
    base_nodes.install_base_nodes(
        comfy_root=str(dst_root),
        source_custom_nodes=None,
        manifest_path=str(manifest_path),
    )

    custom_nodes = dst_root / "custom_nodes"
    assert (custom_nodes / "ComfyUI-WanVideoWrapper" / "marker.txt").read_text(encoding="utf-8")
    assert not (custom_nodes / "comfyui-manager").exists()
    assert {name for name, _url in cloned} == set(base_nodes.BASE_NODE_REPOS)
    assert dict(cloned)["ComfyUI-KJNodes"] == base_nodes.BASE_NODE_REPOS["ComfyUI-KJNodes"]
