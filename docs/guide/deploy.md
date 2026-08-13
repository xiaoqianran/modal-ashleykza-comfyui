# GPU 部署

先 hydrate，再 serve / deploy。GPU 容器只挂载 Volume，不下载模型。工作流锁里的 CNR 节点会打进 Image。

```bash
COMFY_WORKFLOW=examples/z-image-base.json modal serve comfyui_modal.py
COMFY_PROFILE=qwen-image modal deploy comfyui_modal.py
```

| 命令 | 快照 |
|---|---|
| `modal serve` | 不保存 |
| `modal deploy` | 保存，后续冷启动复用 |

换 GPU：`MODAL_GPU=T4`（或 `L4` / `L40S` / `RTX-PRO-6000`）。

锁内 CNR 默认安装。关掉：`COMFY_INSTALL_LOCK_NODES=0`。配方额外节点：`COMFY_INSTALL_NODES=1`。130 个上游基础节点：`COMFY_BASE_NODES=1`。
