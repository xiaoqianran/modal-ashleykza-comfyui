# ComfyUI on Modal

把 [ashleykleynhans/comfyui](https://github.com/ashleykleynhans/comfyui) 部署到 [Modal](https://modal.com)。两种启动方式。GPU Image 对所有工作流共用一层缓存；锁里的 CNR 装到 workspace Volume。130 个上游插件默认不开。

配方出图在顶栏 **[图库](gallery/index.md)**，和文档来回切，不必记单独链接。

## 最短路径

```bash
python -m pip install -U modal
modal secret create comfyui-creds --from-dotenv .env --force
modal run hydrate_modal.py --workflow examples/z-image-base.json
modal serve comfyui_modal.py
```

或按配方：

```bash
modal run hydrate_modal.py --profile qwen-image
modal serve comfyui_modal.py
```

## 约定

| 项 | 默认值 |
|---|---|
| 启动方式 | `--workflow` JSON，或 `--profile` 配方 |
| 插件 | 锁内 CNR 装到 Volume（不重建 Image）；130 个上游 / 配方额外包默认关 |
| GPU App | `comfyui-ashleykza-cu128` |
| Hydrate App | `comfyui-ashleykza-cu128-hydrate` |
| 模型 Volume | `comfyui-ashleykza-models` → `/mnt/comfy-storage` |
| Secret | `comfyui-creds` |
| GPU | T4（L40S 等必须显式 `MODAL_GPU`） |
| 空闲缩容 | 5 秒；`modal serve` / 开着的 UI 会阻止缩容 |

## 阅读顺序

1. [快速开始](getting-started.md)
2. [Hydrate Storage](guide/hydrate.md)
3. [工作流与锁文件](guide/workflows.md)
4. [GPU 部署](guide/deploy.md)
5. [Studio（Z-Image）](guide/studio.md)
6. [环境变量](reference/configuration.md)
7. [配方](guide/recipes.md)
8. [图库](gallery/index.md)
