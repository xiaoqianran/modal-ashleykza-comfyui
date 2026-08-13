import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio.keys import mask_secret, save_keys
from studio.server import _split_prompts


class MaskSecretTests(unittest.TestCase):
    def test_masks_long_token(self):
        self.assertEqual(mask_secret("hf_abcdefghijklmnop"), "hf_a…mnop")

    def test_empty(self):
        self.assertEqual(mask_secret(""), "")


class SplitPromptTests(unittest.TestCase):
    def test_one_per_line(self):
        self.assertEqual(_split_prompts("a\nb\n"), ["a", "b"])

    def test_separator(self):
        text = "line one\nstill one\n---\nsecond"
        self.assertEqual(_split_prompts(text), ["line one\nstill one", "second"])


class SaveKeysTests(unittest.TestCase):
    def test_writes_gitignored_env(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".studio.env"
            with patch("studio.keys.STUDIO_ENV_PATH", path):
                save_keys({"HF_TOKEN": "hf_test_token_value"})
            text = path.read_text(encoding="utf-8")
            self.assertIn("HF_TOKEN=hf_test_token_value", text)
            dumped = json.dumps({"studio": text})
            self.assertNotIn("MODAL_TOKEN_SECRET=", dumped)


if __name__ == "__main__":
    unittest.main()
