# 环境变量

配置集中在 `modal_config.py` 的 `ModalSettings.from_env`。下列变量可在 `modal run` / `modal deploy` / `modal serve` 前导出。

## App 与存储

| 变量 | 默认 | 说明 |
|---|---|---|
| `MODAL_APP_NAME` | `comfyui-ashleykza-cu128` | GPU App 名；hydrate 为 `{name}-hydrate` |
| `MODAL_SECRET_NAME` | `comfyui-creds` | named Secret |
| `MODAL_VOLUME_NAME` | `comfyui-ashleykza-workspace` | workspace Volume |
| `MODAL_MODELS_VOLUME` | `comfyui-ashleykza-models` | 模型 Volume |
| `COMFY_STORAGE_ROOT` | `/mnt/comfy-storage` | 模型 Volume 挂载点 |
| `COMFY_IMAGE` | `ghcr.io/ashleykleynhans/comfyui:cu128-py312-v0.32.0` | 基础镜像。GPU Image 额外 apt：`cmake` `ninja-build` `build-essential` `python3-dev`（仅当 sparse-3d wheel 对不上才编译）。natten / flash-attn / flex_gemm / cumesh / o-voxel 走预构建 wheel |

## GPU 与扩缩容

| 变量 | 默认 | 说明 |
|---|---|---|
| `MODAL_GPU` | `L40S` | 只接受你写明的 GPU。**没有** `L40S,RTX-PRO-6000` 这种静默升级。L40S 没货时任务会失败，而不是改去开 PRO-6000。不要用 T4。正式推理必须显式：`MODAL_GPU=RTX-PRO-6000` |
| `COMFY_SCALEDOWN_SECONDS` | `5` | 空闲后缩容秒数，范围 2–1200 |
| `COMFY_TIMEOUT_SECONDS` | `86400` | 单次输入最长秒数（最长 24h） |
| `COMFY_STARTUP_TIMEOUT_SECONDS` | `900` | 启动探测超时 |
| `COMFY_MAX_INPUTS` | `20` | 单容器最大并发输入 |
| `COMFY_TARGET_INPUTS` | `10` | 扩容阈值（不超过 max） |
| `COMFY_REQUIRE_PROXY_AUTH` | `false` | Modal 代理认证。公网 URL 默认无密码，生产环境请设 `true` |
| `COMFY_MEMORY_SNAPSHOT` | `true` | `modal deploy` 后保存 CPU 快照 |
| `COMFY_GPU_SNAPSHOT` | `true` | GPU 快照；依赖 memory snapshot |

## 启动方式

| 变量 | 默认 | 说明 |
|---|---|---|
| `COMFY_WORKFLOW` | 空 | hydrate 时的工作流 JSON/PNG；写入 Volume `.state/launch.json`。**不要**靠它改 GPU Image |
| `COMFY_PROFILE` | `base` | hydrate 配方名；无 `COMFY_WORKFLOW` 时为 profile 模式 |
| `COMFY_WORKFLOW_LOCK` | 空 | 已有锁文件；workflow 模式默认写成同名 `.lock.json` |
| `COMFY_INSTALL_LOCK_NODES` | `true` | hydrate 写入 launch.json；GPU 启动时往 workspace Volume 装 CNR。`0` / `--skip-lock-nodes` 跳过 |
| `COMFY_INSTALL_NODES` | `false` | `1` 时把配方额外 node packs **打进 Image**（会单独占一层缓存） |
| `COMFY_BASE_NODES` | `false` | `1` 时才克隆约 130 个上游 GitHub 节点（会单独占一层缓存） |
| `COMFY_LATEST` | `false` | `1` 时强制重建节点 Image 层 |
| `EXTRA_ARGS` | 空 | 追加到 ComfyUI 进程的参数 |

## Hydrate

| 变量 | 默认 | 说明 |
|---|---|---|
| `COMFY_HYDRATE_WORKERS` | `4` | 并行下载线程数，范围 1–16 |

Hydrate 容器的 CPU（8）、内存（16 GiB）和超时（6 小时）在 `hydrate_modal.py` 中固定。

## Secret 中的键

`.env.example` 列出常用键，注入 `comfyui-creds`：

- `HF_TOKEN`
- `CIVITAI_TOKEN`
- `GITHUB_TOKEN`
- 可选：`GEMINI_API_KEY`、`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`QWEN_API_KEY`、`OLLAMA_URL`
