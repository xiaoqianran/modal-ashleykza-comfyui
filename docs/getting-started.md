# 快速开始

两种启动方式二选一。本机需要 Python 3.12+。工作流 JSON 锁里的 CNR 装到 workspace Volume，**不会**为每个工作流重建 GPU Image；也**不会**默认去克隆 130 个上游仓库。

## 1. 安装并写入凭证

```bash
python -m pip install -U modal
modal setup
cp .env.example .env   # HF_TOKEN / CIVITAI_TOKEN / GITHUB_TOKEN
modal secret create comfyui-creds --from-dotenv .env --force
```

## 2a. 工作流 JSON

解析 JSON 里的 model 与插件声明，只把**模型**写入 Storage；锁写到 Volume `.state/launch.json`：

```bash
modal run hydrate_modal.py --workflow examples/z-image-base.json
modal serve comfyui_modal.py
```

## 2b. Profile

```bash
modal run hydrate_modal.py --profile qwen-image
modal serve comfyui_modal.py
```

可用名称：`modal run hydrate_modal.py --action profiles`

## 3. 验证

打开 `modal serve` 打印的 `*.modal.run`，加载同一份工作流，Queue Prompt。

生产用 `modal deploy`（才会保存 memory snapshot）。`modal serve` 不保存快照。

插件：锁文件 `custom_nodes` 在 GPU **启动时**装进 `/workspace/custom_nodes`（已存在则跳过）。130 个基础 GitHub 节点仍要 `COMFY_BASE_NODES=1`。配方额外包要 `COMFY_INSTALL_NODES=1`（这两项会改 Image）。
