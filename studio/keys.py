"""Persist studio keys next to the repo. Never commit this file."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO_ENV_PATH = ROOT / ".studio.env"
DOTENV_PATH = ROOT / ".env"

SECRET_KEYS = (
    "HF_TOKEN",
    "CIVITAI_TOKEN",
    "GITHUB_TOKEN",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "QWEN_API_KEY",
    "OLLAMA_URL",
)
MODAL_KEYS = ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
ALL_KEYS = MODAL_KEYS + SECRET_KEYS


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


def load_keys() -> dict[str, str]:
    merged = _parse_env(DOTENV_PATH)
    merged.update(_parse_env(STUDIO_ENV_PATH))
    for key in ALL_KEYS:
        env_value = os.environ.get(key, "").strip()
        if env_value:
            merged[key] = env_value
    return {key: merged[key] for key in ALL_KEYS if merged.get(key)}


def save_keys(updates: dict[str, str]) -> dict[str, str]:
    current = _parse_env(STUDIO_ENV_PATH)
    for key in ALL_KEYS:
        if key not in updates:
            continue
        value = str(updates[key] or "").strip()
        if value:
            current[key] = value
        else:
            current.pop(key, None)
    lines = ["# Local studio keys. Gitignored. Do not commit.", ""]
    for key in ALL_KEYS:
        if current.get(key):
            lines.append(f"{key}={current[key]}")
    STUDIO_ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    STUDIO_ENV_PATH.chmod(0o600)
    return load_keys()


def mask_secret(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "•" * len(text)
    return f"{text[:4]}…{text[-4:]}"


def public_key_state(keys: dict[str, str] | None = None) -> dict[str, object]:
    keys = keys if keys is not None else load_keys()
    configured = {key: bool(keys.get(key)) for key in ALL_KEYS}
    masked = {key: mask_secret(keys[key]) for key in ALL_KEYS if keys.get(key)}
    return {
        "configured": configured,
        "masked": masked,
        "has_hf": bool(keys.get("HF_TOKEN")),
        "has_modal_token": bool(keys.get("MODAL_TOKEN_ID") and keys.get("MODAL_TOKEN_SECRET")),
        "uses_cli_auth": not bool(keys.get("MODAL_TOKEN_ID") and keys.get("MODAL_TOKEN_SECRET")),
    }


def subprocess_env(keys: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    keys = keys if keys is not None else load_keys()
    for key, value in keys.items():
        if value:
            env[key] = value
    local_bin = str(Path.home() / ".local" / "bin")
    env["PATH"] = f"{local_bin}{os.pathsep}{env.get('PATH', '')}"
    return env
