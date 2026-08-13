# GPU 部署

先 hydrate，再 serve / deploy。GPU 容器挂载 Volume：`snap=False` 时 `reload()` 后读 `.state/launch.json`，把锁内 CNR 装到 workspace（已存在则跳过）。**不要**把工作流打进 Image，否则 Modal 层缓存每次都 miss。

```bash
modal serve comfyui_modal.py
modal deploy comfyui_modal.py
```

| 命令 | 快照 |
|---|---|
| `modal serve` | 不保存 |
| `modal deploy` | 保存，后续冷启动复用 |

换 GPU：`MODAL_GPU=T4`（或 `L4` / `L40S` / `RTX-PRO-6000`）。

锁内 CNR 默认在 GPU 启动时装到 Volume。关掉：hydrate 时 `--skip-lock-nodes`。配方额外节点：`COMFY_INSTALL_NODES=1`（改 Image）。130 个上游基础节点：`COMFY_BASE_NODES=1`（改 Image）。
