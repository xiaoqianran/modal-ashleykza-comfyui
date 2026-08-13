# modal-ashleykza-comfyui

在 Modal 上跑 ComfyUI。两种启动方式；**默认不装插件**。

**文档：** [https://xiaoqianran.github.io/modal-ashleykza-comfyui/](https://xiaoqianran.github.io/modal-ashleykza-comfyui/)

```bash
python -m pip install -U modal
modal setup
cp .env.example .env
modal secret create comfyui-creds --from-dotenv .env --force
```

## 两种启动方式

**1. 工作流 JSON** — 解析里面的 model 和插件，只下载模型：

```bash
modal run hydrate_modal.py --workflow examples/z-image-base.json
COMFY_WORKFLOW=examples/z-image-base.json modal serve comfyui_modal.py
```

**2. Profile** — 按 `recipes.py` 里的配方拉模型包：

```bash
modal run hydrate_modal.py --profile qwen-image
COMFY_PROFILE=qwen-image modal serve comfyui_modal.py
```

插件会写进 `.lock.json`，但 **不会安装**。以后需要时再开 `COMFY_INSTALL_NODES=1`（以及可选的 `COMFY_BASE_NODES=1`）。

空闲 **5 秒** 缩掉 GPU。`modal deploy` 才保存 snapshot。列表：`modal run hydrate_modal.py --action profiles`

## 开发

```bash
python -m unittest discover -s tests -v
```
