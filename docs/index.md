# ComfyUI on Modal

把 [ashleykleynhans/comfyui](https://github.com/ashleykleynhans/comfyui) 部署到 [Modal](https://modal.com)。权重由 CPU 写入 **Volume**，GPU 容器只挂载、校验、推理，启动路径里不下载模型。

## 最短路径

```bash
python -m pip install -U modal
modal secret create comfyui-creds --from-dotenv .env --force
modal run hydrate_modal.py --action hydrate --workflow examples/z-image-base.json
COMFY_BASE_NODES=0 MODAL_GPU=L4 modal deploy comfyui_modal.py
```

打开 `modal deploy` 打印的 `*.modal.run` 地址，在 UI 里加载同一份工作流。

## 约定

| 项 | 默认值 |
|---|---|
| GPU App | `comfyui-ashleykza-cu128`（`comfyui_modal.py`） |
| Hydrate App | `comfyui-ashleykza-cu128-hydrate`（`hydrate_modal.py`） |
| 模型 Volume | `comfyui-ashleykza-models` → `/mnt/comfy-storage` |
| 工作区 Volume | `comfyui-ashleykza-workspace` → `/workspace` |
| Secret | `comfyui-creds` |
| GPU | 未设置 `MODAL_GPU` 时按 `T4 → L4 → L40S → RTX-PRO-6000` 回退 |
| 空闲缩容 | 5 秒（`COMFY_SCALEDOWN_SECONDS`） |

Hydrate 是独立 CPU App：`modal run hydrate_modal.py` **不会**构建 GPU Image，也**不会**克隆自定义节点仓库。

## 阅读顺序

1. [快速开始](getting-started.md) — 安装、凭证、第一次出图
2. [核心概念](guide/concepts.md) — 两个 App、Volume、快照
3. [Hydrate Storage](guide/hydrate.md) — 把权重写入 Volume
4. [工作流与锁文件](guide/workflows.md) — 解析依赖、补全 URL
5. [GPU 部署](guide/deploy.md) — `deploy` / `serve`、节点与缩容
6. [环境变量](reference/configuration.md) — `modal_config.py` 全表
