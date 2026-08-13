# Hydrate Storage

Hydrate 把权重写进 Volume `comfyui-ashleykza-models`。只使用 CPU，镜像是 `debian-slim` + `aria2` + `huggingface_hub`，不构建 GPU Image。

## 命令

```bash
# 按工作流下载（已存在则跳过）
modal run hydrate_modal.py --action hydrate --workflow examples/z-image-base.json

# 按配方下载
modal run hydrate_modal.py --action hydrate --profile qwen-image

# 只解析、写出锁文件，不下载
modal run hydrate_modal.py --action resolve --workflow examples/z-image-base.json

# 列出配方
modal run hydrate_modal.py --action profiles

# 打印 App / Volume / worker 信息
modal run hydrate_modal.py --action info
```

`hydrate` 与 `sync` / `workflow-sync` 等价：有 `--workflow` 时按锁文件同步；没有 `--workflow` 时按 `--profile`（默认 `COMFY_PROFILE`，否则 `base`）。

| 参数 | 说明 |
|---|---|
| `--action` | `hydrate`、`sync`、`workflow-sync`、`resolve`、`profiles`、`info` |
| `--workflow` | 工作流 JSON 或 PNG |
| `--profile` | `recipes.py` 中的配方名 |
| `--lock-out` | 锁文件输出路径；默认把工作流后缀改成 `.lock.json` |

## 并行与资源

默认 4 路并行下载（`COMFY_HYDRATE_WORKERS`，范围 1–16）。容器为 8 CPU / 16 GiB，超时 6 小时，`max_containers=1`。下载失败会按 `modal.Retries` 指数退避重试。

```bash
COMFY_HYDRATE_WORKERS=8 modal run hydrate_modal.py \
  --action hydrate --workflow examples/z-image-base.json
```

## 路径规则

下载目标始终是 `/mnt/comfy-storage/<category>/<filename>`。

`<category>` 必须是 ComfyUI 模型目录名，例如 `diffusion_models`、`text_encoders`、`vae`。不要写成随意别名；`recipes.MODEL_DIRS` 列出了全部合法值。

## 幂等

- 目标文件已存在且 URL / 大小（或 SHA256）匹配 → `[SKIP]`
- 旧 workspace 有文件、Storage 没有 → `[PROMOTE]`，不重新下载
- 每完成一个文件就更新 `/mnt/comfy-storage/.state/comfy.lock.json`
- Function 成功后对 **models + workspace** 两个 Volume 都 `commit()`

Modal Volume 对已运行容器采用快照式可见性。hydrate 完成后再 `deploy` / 开新容器，不要指望正在跑的 GPU 容器立刻看到新文件。

## 凭证

Hydrate 与 GPU 共用 Secret `comfyui-creds`。Hugging Face / Civitai 下载需要对应 token。
