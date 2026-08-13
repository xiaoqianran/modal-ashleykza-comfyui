# modal-ashleykza-comfyui

在 Modal 上跑 ComfyUI。模型先用 CPU 写入 Storage，GPU 只推理，不下载。

**文档：** [https://xiaoqianran.github.io/modal-ashleykza-comfyui/](https://xiaoqianran.github.io/modal-ashleykza-comfyui/)

```bash
python -m pip install -U modal
modal setup
cp .env.example .env   # 填 HF_TOKEN / CIVITAI_TOKEN / GITHUB_TOKEN
modal secret create comfyui-creds --from-dotenv .env --force
```

## 用法

```bash
# 1. CPU 把模型拉进 Modal Storage（无 GPU）
modal run hydrate_modal.py --action hydrate --workflow examples/z-image-base.json
# 或按 Profile：
modal run hydrate_modal.py --action hydrate --profile qwen-image

# 2. 部署 GPU UI（deploy 才会保存 memory snapshot）
COMFY_BASE_NODES=0 MODAL_GPU=L4 modal deploy comfyui_modal.py
```

空闲 **5 秒** 缩掉 GPU。`modal serve` 方便调试，但不保存快照。

只解析、不下载：

```bash
modal run hydrate_modal.py --action resolve --workflow workflow.json
```

列表：`modal run hydrate_modal.py --action profiles`

## 开发

```bash
python -m unittest discover -s tests -v
python -m pip install -r docs/requirements.txt && mkdocs serve
```
