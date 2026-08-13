# modal-ashleykza-comfyui

在 Modal 上跑 ComfyUI。模型先用 CPU 写入 Storage，GPU 只推理，不下载。

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

## 存储

| 位置 | 内容 |
|---|---|
| Volume `comfyui-ashleykza-models` → `/mnt/comfy-storage/<category>/` | 模型（和 ComfyUI 目录同名） |
| Volume `comfyui-ashleykza-workspace` → `/workspace` | input / output / user / logs |
| Image `/ComfyUI` | 运行时和 custom nodes |

## 常用变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `MODAL_GPU` | `T4,L4,L40S,RTX-PRO-6000` | GPU 顺序 |
| `COMFY_PROFILE` | `base` | `recipes.py` 里的组合 |
| `COMFY_BASE_NODES` | `true` | `0` 跳过 130 个 GitHub 节点 |
| `COMFY_WORKFLOW_LOCK` | 空 | 部署时嵌入的锁文件 |
| `COMFY_SCALEDOWN_SECONDS` | `5` | 空闲多久关 GPU |
| `COMFY_LATEST` | `false` | `1` 强制重建节点 Image |
| `COMFY_MEMORY_SNAPSHOT` | `true` | deploy 后加快照 |
| `MODAL_SECRET_NAME` | `comfyui-creds` | named Secret |

## 开发

```bash
python -m unittest discover -s tests -v
```

细节：[`docs/STORAGE.md`](docs/STORAGE.md) · [`docs/WORKFLOW_PREFETCH.md`](docs/WORKFLOW_PREFETCH.md) · 改模型/节点看 `recipes.py`
