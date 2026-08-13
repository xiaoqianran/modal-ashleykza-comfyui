# GPU 部署

先 hydrate，再 serve / deploy。GPU 容器只挂载 Volume，不下载模型，默认不装插件。

```bash
COMFY_WORKFLOW=examples/z-image-base.json modal serve comfyui_modal.py
COMFY_PROFILE=qwen-image modal deploy comfyui_modal.py
```

| 命令 | 快照 |
|---|---|
| `modal serve` | 不保存 |
| `modal deploy` | 保存，后续冷启动复用 |

换 GPU：`MODAL_GPU=T4`（或 `L4` / `L40S` / `RTX-PRO-6000`）。

以后要装工作流 / 配方里的节点：`COMFY_INSTALL_NODES=1`。要 130 个上游基础节点：`COMFY_BASE_NODES=1`。两者默认都是关。
