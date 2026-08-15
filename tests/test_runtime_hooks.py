import unittest
from pathlib import Path

from runtime_hooks import (
    RUNTIME_HOOKS,
    hook_named,
    matched_hooks,
    sam3d_matches,
    sparse_3d_matches,
)


class RuntimeHookTableTests(unittest.TestCase):
    def test_table_has_sparse_and_sam3d_only(self):
        self.assertEqual([hook.name for hook in RUNTIME_HOOKS], ["sparse-3d", "sam3d"])

    def test_empty_lock_matches_nothing(self):
        self.assertEqual(matched_hooks([]), ())
        self.assertFalse(sparse_3d_matches([]))
        self.assertFalse(sam3d_matches([]))

    def test_pixal3d_and_trellis2_share_sparse_hook(self):
        pixal = matched_hooks([{"id": "Pixal3D-ComfyUI"}])
        trellis = matched_hooks([{"id": "ComfyUI-Trellis2"}])
        self.assertEqual([hook.name for hook in pixal], ["sparse-3d"])
        self.assertEqual([hook.name for hook in trellis], ["sparse-3d"])
        workspace = Path("/workspace")
        self.assertEqual(
            hook_named("sparse-3d").wheels_kwargs([{"id": "Pixal3D-ComfyUI"}], workspace),
            {
                "include_attention": True,
                "include_sparse": True,
                "include_drtk": True,
                "include_nvdiffrast": False,
                "workspace": workspace,
            },
        )
        self.assertEqual(
            hook_named("sparse-3d").wheels_kwargs([{"id": "ComfyUI-Trellis2"}], workspace),
            {
                "include_attention": False,
                "include_sparse": True,
                "include_drtk": False,
                "include_nvdiffrast": True,
                "workspace": workspace,
            },
        )

    def test_sam3d_does_not_pull_sparse_wheels(self):
        hooks = matched_hooks([{"id": "ComfyUI-SAM3DObjects"}])
        self.assertEqual([hook.name for hook in hooks], ["sam3d"])
        self.assertIsNone(hooks[0].ensure_wheels)
        self.assertEqual(hooks[0].prepare, "apply_comfy_env_root")
        self.assertEqual(hooks[0].ensure_runtime, "ensure_sam3d_runtime")

    def test_unknown_hook_name_raises(self):
        with self.assertRaises(KeyError):
            hook_named("megapak")


if __name__ == "__main__":
    unittest.main()
