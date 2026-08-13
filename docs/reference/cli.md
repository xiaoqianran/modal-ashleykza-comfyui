# 命令行

## hydrate_modal.py

CPU App，只下载模型。

```bash
modal run hydrate_modal.py --workflow examples/z-image-base.json
modal run hydrate_modal.py --profile qwen-image
modal run hydrate_modal.py --action resolve --workflow workflow.json
modal run hydrate_modal.py --action profiles
```

| 参数 | 说明 |
|---|---|
| `--workflow` | 工作流 JSON / PNG（workflow 模式） |
| `--profile` | 配方名（profile 模式，默认 `base`） |
| `--lock-out` | 锁文件路径 |
| `--skip-lock-nodes` | GPU 启动时跳过锁内 CNR |
| `--action` | `hydrate`（默认）、`resolve`、`profiles`、`info` |

## comfyui_modal.py

```bash
modal serve comfyui_modal.py
modal deploy comfyui_modal.py
modal run comfyui_modal.py
```

不要用 GPU App 做 hydrate。

## Volume

```bash
modal volume ls comfyui-ashleykza-models
modal volume get comfyui-ashleykza-workspace /output ./output
```
