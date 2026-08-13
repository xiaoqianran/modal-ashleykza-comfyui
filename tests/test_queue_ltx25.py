import importlib.util
import unittest
from pathlib import Path


def _load_queue_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "queue_ltx25.py"
    spec = importlib.util.spec_from_file_location("queue_ltx25", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Ltx25WorkflowPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_queue_module()

    def test_replaces_missing_032_nodes_and_rewires_api_switch(self):
        workflow = {
            "nodes": [],
            "definitions": {
                "subgraphs": [
                    {
                        "id": "input",
                        "nodes": [
                            {
                                "id": 5504,
                                "type": "GemmaAPITextEncode",
                                "mode": 0,
                                "inputs": [],
                                "outputs": [
                                    {"name": "conditioning", "type": "CONDITIONING", "links": [13785]}
                                ],
                                "widgets_values": ["", ""],
                            },
                            {
                                "id": 1241,
                                "type": "LTXVConditioning",
                                "mode": 0,
                                "inputs": [],
                                "outputs": [
                                    {"name": "positive", "type": "CONDITIONING", "links": [13786]},
                                    {"name": "negative", "type": "CONDITIONING", "links": [13789]},
                                ],
                            },
                            {
                                "id": 5558,
                                "type": "ComfySwitchNode",
                                "mode": 0,
                                "inputs": [
                                    {"name": "on_false", "type": "CONDITIONING", "link": 13786},
                                    {"name": "on_true", "type": "CONDITIONING", "link": 13785},
                                ],
                            },
                            {
                                "id": 5000,
                                "type": "LTXFloatToInt",
                                "mode": 0,
                                "inputs": [{"name": "a", "type": "FLOAT", "widget": {"name": "a"}, "link": 1}],
                                "outputs": [{"name": "INT", "type": "INT", "links": [13424]}],
                            },
                            {
                                "id": 5572,
                                "type": "UNETLoader",
                                "widgets_values": [
                                    "ltx-2.5-22b-dev-transformer-bf16.safetensors",
                                    "default",
                                ],
                            },
                        ],
                        "links": [
                            {
                                "id": 13785,
                                "origin_id": 5504,
                                "origin_slot": 0,
                                "target_id": 5558,
                                "target_slot": 1,
                                "type": "CONDITIONING",
                            },
                            {
                                "id": 13786,
                                "origin_id": 1241,
                                "origin_slot": 0,
                                "target_id": 5558,
                                "target_slot": 0,
                                "type": "CONDITIONING",
                            },
                            {
                                "id": 13424,
                                "origin_id": 5000,
                                "origin_slot": 0,
                                "target_id": 3980,
                                "target_slot": 2,
                                "type": "INT",
                            },
                        ],
                    }
                ]
            },
        }
        patched = self.mod.patch_workflow(workflow)
        subgraph = patched["definitions"]["subgraphs"][0]
        by_id = {node["id"]: node for node in subgraph["nodes"]}
        self.assertEqual(by_id[5504]["type"], "CLIPTextEncode")
        self.assertEqual(by_id[5504]["mode"], 2)
        self.assertEqual(by_id[5000]["type"], "ComfyNumberConvert")
        self.assertEqual(by_id[5000]["outputs"][1]["name"], "INT")
        self.assertEqual(by_id[5572]["widgets_values"][0], "ltx-2.5-22b-distilled-transformer-bf16.safetensors")
        api_link = next(link for link in subgraph["links"] if link["id"] == 13785)
        self.assertEqual(api_link["origin_id"], 1241)
        int_link = next(link for link in subgraph["links"] if link["id"] == 13424)
        self.assertEqual(int_link["origin_slot"], 1)


if __name__ == "__main__":
    unittest.main()
