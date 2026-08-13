# modal-ashleykza-comfyui

在 Modal 上跑 ComfyUI。两种启动方式。

**文档：** [https://xiaoqianran.github.io/modal-ashleykza-comfyui/](https://xiaoqianran.github.io/modal-ashleykza-comfyui/)

```bash
python -m pip install -U modal
modal setup
cp .env.example .env
modal secret create comfyui-creds --from-dotenv .env --force
```

## 两种启动方式

**1. 工作流 JSON** — 解析 model 和插件；下载模型；锁里的 CNR 节点在 GPU Image 安装：

```bash
modal run hydrate_modal.py --workflow examples/z-image-base.json
COMFY_WORKFLOW=examples/z-image-base.json modal serve comfyui_modal.py
```

**2. Profile** — 按 `recipes.py` 拉模型包（配方额外插件默认不装）：

```bash
modal run hydrate_modal.py --profile qwen-image
COMFY_PROFILE=qwen-image modal serve comfyui_modal.py
```

130 个上游 GitHub 节点默认不开。需要时：`COMFY_BASE_NODES=1`。配方额外包：`COMFY_INSTALL_NODES=1`。关掉锁内节点：`COMFY_INSTALL_LOCK_NODES=0`。

空闲 **5 秒** 缩掉 GPU。`modal deploy` 才保存 snapshot。列表：`modal run hydrate_modal.py --action profiles`

## 开发

```bash
python -m unittest discover -s tests -v
```
