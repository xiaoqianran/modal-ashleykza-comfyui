# 命令行

## hydrate_modal.py

CPU App，只下载模型。

```bash
modal run hydrate_modal.py --workflow examples/z-image-base.json
modal run hydrate_modal.py --profile qwen-image
modal run hydrate_modal.py --action resolve --workflow workflow.json
modal run hydrate_modal.py --action profiles
modal run hydrate_modal.py --action outputs
modal run hydrate_modal.py --action repair
```

| 参数 | 说明 |
|---|---|
| `--workflow` | 工作流 JSON / PNG（workflow 模式） |
| `--profile` | 配方名（profile 模式，默认 `base`） |
| `--lock-out` | 锁文件路径 |
| `--skip-lock-nodes` | GPU 启动时跳过锁内 CNR |
| `--install-nodes` | **无效**（hydrate 不构建 GPU Image）。配方额外包请在 serve/deploy 时设 `COMFY_INSTALL_NODES=1` |
| `--action` | `hydrate`（默认）、`sync` / `workflow-sync`（同 hydrate）、`resolve`、`profiles`、`info`、`outputs`、`repair` |

## comfyui_modal.py

```bash
modal serve comfyui_modal.py
modal deploy comfyui_modal.py
modal run comfyui_modal.py
```

不要用 GPU App 做 hydrate。

## studio

```bash
python -m studio
```

本机 `127.0.0.1:8787`。见 [Studio](../guide/studio.md)。

## Volume

```bash
modal volume ls comfyui-ashleykza-models
modal volume get comfyui-ashleykza-workspace /output ./output
```
