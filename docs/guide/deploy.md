# GPU 部署

## deploy 与 serve

| 命令 | 用途 | Memory snapshot |
|---|---|---|
| `modal deploy comfyui_modal.py` | 生产 / 持久 URL | 会保存，后续冷启动复用 |
| `modal serve comfyui_modal.py` | 本地开发热重载 | **不会**持久化快照 |

```bash
COMFY_BASE_NODES=0 MODAL_GPU=L4 modal deploy comfyui_modal.py
```

首次 `deploy` 的冷启动会捕获快照（每种 GPU worker 前 2–3 次多花几十秒）。之后同 GPU 类型的冷启动会跳过大部分进程初始化。权重从 Volume 装进 VRAM 仍可能要数十秒：这是存储带宽限制，快照不会消除。

快照没有单独产品加价，只付实际 GPU 秒数。关掉：`COMFY_MEMORY_SNAPSHOT=0`。只关 GPU 快照：`COMFY_GPU_SNAPSHOT=0`。

## Image 与节点

默认会安装上游基础节点（约 130 个 GitHub 仓库）。第一次构建可能很慢。

| 变量 | 作用 |
|---|---|
| `COMFY_BASE_NODES=0` | 只留 comfy-core，跳过那 130 个克隆 |
| `COMFY_LATEST=1` | 强制重建节点 Image 层；默认关闭，复用缓存 |
| `COMFY_PROFILE` | 额外的模型包 / 节点包，见 [配方](recipes.md) |

Z-Image 这类 comfy-core 工作流用 `COMFY_BASE_NODES=0` 即可。

## GPU 选择

未设置时按 `T4,L4,L40S,RTX-PRO-6000` 回退。生产建议显式指定：

```bash
MODAL_GPU=L4 modal deploy comfyui_modal.py
```

`MODAL_GPU` 支持逗号分隔的 fallback 列表。更换 GPU 类型后，该类型会各自捕获一份 snapshot。

## 缩容

默认空闲 **5 秒** 缩到 0（`COMFY_SCALEDOWN_SECONDS`，范围 2–1200）。ComfyUI 保持 `max_containers=1`。

## Web UI

`@modal.web_server` 暴露 ComfyUI（默认端口 3000）。HTTPS 由 Modal 提供。需要代理认证时打开 `COMFY_REQUIRE_PROXY_AUTH=1`。
