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
modal run hydrate_modal.py --catalog z-image
# 或 modal run hydrate_modal.py --workflow examples/z-image-base.json
MODAL_GPU=L40S modal serve comfyui_modal.py
```

默认 GPU 是 L40S，不要用 T4。测完 **Ctrl+C** 停掉 serve；只把页面开着会阻止 5 秒缩容。

## 2b. 旧 Profile

Studio 不用 `recipes.PROFILES`。只有下载 nordy / wan / ltx23 这类旧模型包时才用：

```bash
modal run hydrate_modal.py --profile qwen-image
modal serve comfyui_modal.py
```

`--action profiles` 会说明这一点，并同时列出 Studio catalog id。

## 3. 验证

打开 `modal serve` 打印的 `*.modal.run`，加载同一份工作流，Queue Prompt。也可以 `python -m studio` 或双击 `open-studio.bat`：打开后默认 Z-Image 表单，顶栏可换配方（见 [Studio](guide/studio.md)）。没有 Python 的 Windows 机器下载 Releases 里的这一个 `Studio.exe`，双击即可。

生产用 `modal deploy`（才会保存 memory snapshot）。`modal serve` 不保存快照。

插件：锁文件 `custom_nodes` 在 GPU **启动时**装进 `/workspace/custom_nodes`（已存在则跳过）。130 个基础 GitHub 节点仍要 `COMFY_BASE_NODES=1`。配方额外包要 `COMFY_INSTALL_NODES=1`（这两项会改 Image）。
