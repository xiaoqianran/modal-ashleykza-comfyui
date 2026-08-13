# 命令行

## hydrate_modal.py

独立 CPU App。**始终**用这个文件做下载，避免构建 GPU Image。

```bash
modal run hydrate_modal.py --action <action> [选项]
```

| `--action` | 行为 |
|---|---|
| `hydrate` / `sync` | 无 `--workflow`：按 `--profile` 下载模型包；有 `--workflow`：解析并下载 |
| `workflow-sync` | 必须给 `--workflow`，解析并下载 |
| `resolve` | 只写锁文件，不下载 |
| `profiles` | 打印配方表 |
| `info` | 打印 App 名、Volume、worker 数 |

| 选项 | 说明 |
|---|---|
| `--profile` | 配方名，默认 `COMFY_PROFILE` |
| `--workflow` | 工作流 JSON 或 PNG |
| `--lock-out` | 锁文件输出路径 |

## comfyui_modal.py

```bash
modal deploy comfyui_modal.py
modal serve comfyui_modal.py
modal run comfyui_modal.py --action info
```

`modal run comfyui_modal.py --action hydrate|resolve|profiles` 仍然可用，但会加载 GPU App（含 Runtime Image）。预取模型请改用 `hydrate_modal.py`。

## Volume

```bash
modal volume ls comfyui-ashleykza-models
modal volume ls comfyui-ashleykza-workspace
```

## 测试

```bash
python -m unittest discover -s tests -v
```
