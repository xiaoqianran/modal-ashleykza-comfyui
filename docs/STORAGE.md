# Modal Storage hydrate

模型权重不进 GPU 启动路径，也不烘焙进 Image。CPU Function 把它们写进 Modal 自己的 Volume；GPU 只挂载、校验、读取。

## 为什么以前看起来“下载很久”

1. 权重本身很大（例如 Z-Image bf16 UNET + Qwen 3 4B text encoder），第一次填充空 Volume 必须走公网。
2. 旧路径把模型写进 workspace Volume，而且是**串行**下载。
3. 曾经 `modal serve` 默认 `force_build`，每次冷启动都重克隆约 130 个 GitHub 节点，看起来像一直在下载。
4. GPU 容器如果缺文件再补下，会按 GPU 单价计费。

现在：`COMFY_LATEST` 必须显式打开才会重建节点层；模型走独立 Storage Volume；hydrate 默认 4 路并行；GPU 缺文件直接失败。

## Volume 与 ComfyUI 路径映射

| Modal Volume | 容器挂载点 | 用途 |
|---|---|---|
| `comfyui-ashleykza-models` | `/mnt/comfy-storage` | 模型权重（只由 CPU hydrate 写入） |
| `comfyui-ashleykza-workspace` | `/workspace` | input / output / user / logs / 实验节点 |

Storage 目录名与 ComfyUI `models/<category>/` **同名**：

```text
/mnt/comfy-storage/vae/ae.safetensors
/mnt/comfy-storage/text_encoders/qwen_3_4b.safetensors
/mnt/comfy-storage/diffusion_models/z_image_bf16.safetensors
/mnt/comfy-storage/.state/comfy.lock.json
```

GPU 启动时写入 `extra_model_paths.yaml`：

```yaml
modal_storage:
    base_path: /mnt/comfy-storage
    is_default: true
    vae: vae/
    text_encoders: text_encoders/
    diffusion_models: diffusion_models/
    # ...其余 MODEL_DIRS
modal_workspace:
    base_path: /workspace
    is_default: false
    vae: models/vae/
    custom_nodes: custom_nodes/
```

ComfyUI 因此用和本地一样的文件名（`ae.safetensors`、`qwen_3_4b.safetensors`）从 Volume 里解析模型。workspace `models/` 只作为旧数据回退；hydrate 若发现旧文件会复制进 Storage，不再重新下载。

## 命令

把工作流依赖拉进 Modal Storage（CPU，无 GPU）：

```bash
modal run hydrate_modal.py \
  --action hydrate \
  --workflow examples/z-image-base.json
```

按 Profile hydrate：

```bash
modal run hydrate_modal.py --action hydrate --profile qwen-image
```

`sync` / `workflow-sync` 仍可用，写入的是同一 Storage Volume。

加速并行（默认 4，最大 16）：

```bash
COMFY_HYDRATE_WORKERS=8 modal run hydrate_modal.py \
  --action hydrate \
  --workflow examples/z-image-base.json
```

CPU hydrate 使用独立 App `hydrate_modal.py`，只构建 debian-slim 下载镜像。GPU ComfyUI Image 只在 `modal serve` / `modal deploy comfyui_modal.py` 时构建。GPU 启动前请先 hydrate，不要在 GPU 容器里等下载。Z-Image bf16 建议：

```bash
COMFY_BASE_NODES=0 MODAL_GPU=L4 modal serve comfyui_modal.py
```

`COMFY_BASE_NODES=0` 跳过 130 个 GitHub 节点克隆，适合只跑 comfy-core 工作流。需要刷新节点 Image 时再设 `COMFY_LATEST=1`。

## Memory Snapshot

`modal deploy` 后，GPU UI 会给容器做 CPU + GPU memory snapshot。`modal serve` 不会保存快照。

- 前 2–3 次冷启动会稍慢（给每种 GPU worker 建快照），按 L4 大约每次多几十秒，合计大约 **$0.05–$0.15 一次性**。
- 之后从快照恢复，ComfyUI 进程启动那 ~90s 可以砍掉一大截。首张把 safetensors 装进显存（~50s）官方说不一定更快。
- 快照没有单独加价；只付实际 GPU 秒数。恢复更快时，每次冷启动通常更省。
- 关掉：`COMFY_MEMORY_SNAPSHOT=0`。只关 GPU 快照：`COMFY_GPU_SNAPSHOT=0`。
- 空闲 **5 秒** 后缩掉 GPU（`COMFY_SCALEDOWN_SECONDS`，Modal 下限 2 秒）。

```bash
COMFY_BASE_NODES=0 MODAL_GPU=L4 modal deploy comfyui_modal.py
```

## 幂等

- 目标文件已存在且 URL/大小（或 SHA256）匹配则 `[SKIP]`；
- 旧 workspace 有文件、Storage 没有则 `[PROMOTE]`；
- 每完成一个文件就更新 `/mnt/comfy-storage/.state/comfy.lock.json`；
- Function 成功后对两个 Volume 都 `commit()`。
