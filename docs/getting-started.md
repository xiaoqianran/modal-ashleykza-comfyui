# 快速开始

把一个 ComfyUI 工作流跑到 Modal GPU 上，按下面四步即可。本机需要 Python 3.10+。

## 1. 安装 Modal CLI

```bash
python -m pip install -U modal
modal setup
```

## 2. 写入凭证

复制仓库根目录的 `.env.example` 为 `.env`，按需填写：

| 变量 | 用途 |
|---|---|
| `HF_TOKEN` | Hugging Face（gated / 私有仓库需要） |
| `CIVITAI_TOKEN` | Civitai 受限下载 |
| `GITHUB_TOKEN` | 可选；提高克隆节点仓库的 GitHub 限额 |

创建同名 Secret。名称必须是 `comfyui-creds`（可用 `MODAL_SECRET_NAME` 覆盖）：

```bash
modal secret create comfyui-creds --from-dotenv .env --force
```

不要把 `.env` 提交进 Git。

## 3. Hydrate（CPU，写 Storage）

```bash
modal run hydrate_modal.py --action hydrate --workflow examples/z-image-base.json
```

该命令会：

- 启动独立 App `comfyui-ashleykza-cu128-hydrate`（CPU，debian-slim，不构建 GPU Image）
- 解析工作流，写出 `examples/z-image-base.lock.json`
- 把已解析的权重并行写入 Volume `comfyui-ashleykza-models`
- 已存在且匹配的文件跳过（`[SKIP]`）；旧 workspace 布局会提升到 Storage（`[PROMOTE]`）

只解析、不下载：

```bash
modal run hydrate_modal.py --action resolve --workflow examples/z-image-base.json
```

查看 Volume：

```bash
modal volume ls comfyui-ashleykza-models
```

## 4. 部署 GPU UI

```bash
COMFY_BASE_NODES=0 MODAL_GPU=L4 modal deploy comfyui_modal.py
```

打开终端打印的 `https://….modal.run`。

!!! warning "快照只在 deploy 后生效"
    GPU memory snapshot 只在 `modal deploy` 之后跨冷启动复用。`modal serve` 每次冷启动都会重新初始化 ComfyUI。

## 验证

1. 在 UI 中加载 `examples/z-image-base.json`
2. Queue Prompt
3. 输出出现在 `SaveImage` 节点

若 Loader 报缺模型，先 `modal volume ls comfyui-ashleykza-models`，再看 [故障排除](troubleshooting.md)。

## 常用变体

=== "开发热重载"

    ```bash
    COMFY_BASE_NODES=0 MODAL_GPU=L4 modal serve comfyui_modal.py
    ```

    代码变更会热更新。**不保存** snapshot。

=== "换 GPU"

    ```bash
    COMFY_BASE_NODES=0 MODAL_GPU=L40S modal deploy comfyui_modal.py
    ```

    每种 GPU 类型会各自捕获一份 snapshot。

=== "按配方 hydrate"

    ```bash
    modal run hydrate_modal.py --action hydrate --profile qwen-image
    ```

    可用名称见 [配方](guide/recipes.md)。
