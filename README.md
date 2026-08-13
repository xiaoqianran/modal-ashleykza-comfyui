# modal-ashleykza-comfyui

把原来的 ComfyUI Docker / Jupyter Notebook 操作拆成可维护的 **Recipe → Build → Sync → Run** 架构。

## 设计

```text
recipes.py
   │
   ├── MODEL_PACKS     模型 URL / 分类
   ├── NODE_PACKS      custom node 仓库 / requirements / 安装动作
   └── PROFILES        一个可直接运行的组合
          │
          ▼
comfy_engine.py
   ├── build_node_commands()   节点 → Image build
   ├── sync_profile_models()   模型 → Modal Volume（CPU）
   ├── comfy.lock.json         幂等下载状态
   └── prepare_runtime()       extra_model_paths + mutable state
          │
          ▼
comfyui_modal.py
   ├── CPU sync_models()
   └── GPU ui()
```

### 存储边界

- **Image（不可变）**：`/ComfyUI`、venv、CUDA / torch、选中 Profile 的稳定 custom nodes。
- **Volume（可变）**：`/workspace/models`、`input`、`output`、`user`、`custom_nodes`、`logs`、`state/comfy.lock.json`。
- `/ComfyUI/models` 不被覆盖；通过 `extra_model_paths.yaml` 让 ComfyUI 同时读取 `/workspace/models`。
- `/workspace/custom_nodes` 作为额外节点目录保留，适合实验节点；稳定节点建议写进 `NODE_PACKS` 后重新 deploy。

## 已迁移的 Notebook 功能

### Model Profiles

- `ltx23`
- `nordy-kontext-views`
- `nordy-clothes`
- `qwen-image`
- `flux-krea`
- `flux-kontext`
- `wan22`
- `wan22-notebook-full`

### Node Packs

- Nordy 换衣节点组
- Qwen Image
- omini-kontext
- Wan 2.2 core
- Wan Notebook 全量节点组
- Nunchaku

旧 Notebook 中 Docker `run/exec/restart`、gradio-tunneling、zrok、`nvidia-smi --gpu-reset` 等操作不再放进部署代码：Modal 已负责容器生命周期和 Web endpoint。

Notebook 中硬编码的 HF / Civitai / Gemini credential **没有迁移到 Git**。

## 1. 安装 / 登录 Modal

```bash
pip install -U modal
modal setup
```

## 2. 查看 Profile

```bash
modal run comfyui_modal.py --action profiles
```

## 3. 先同步模型（CPU，不占 GPU）

例如 Qwen Image：

```bash
modal run comfyui_modal.py --action sync --profile qwen-image
```

Wan 2.2：

```bash
modal run comfyui_modal.py --action sync --profile wan22
```

下载写入：

```text
/workspace/models/...
/workspace/state/comfy.lock.json
```

再次运行同一个 sync 时，已记录且文件大小一致的资产会跳过；Recipe 可选填写 `sha256=` 进行强校验。

## 下载策略：当前默认为什么这样设计

模型同步阶段不占 GPU，下载完成后长期保存在 Modal Volume。当前默认路由：

```text
Hugging Face  → huggingface_hub / hf_xet（HF_XET_HIGH_PERFORMANCE=1）
Civitai       → aria2c -x16 -s16
普通 HTTP(S)  → aria2c -x16 -s16
                 ↓
            Modal Volume
                 ↓
         GPU 只加载 / 推理
```

这是为了避免每次 GPU 冷启动重新下载模型。`hf_xet` 是当前 Hugging Face 的主下载后端；如果 HF/Xet 下载异常，引擎会回退到 aria2。

## 4. 启动 UI

第一次测试：

```bash
COMFY_PROFILE=qwen-image modal serve comfyui_modal.py
```

持久 endpoint：

```bash
COMFY_PROFILE=qwen-image modal deploy comfyui_modal.py
```

Windows PowerShell：

```powershell
$env:COMFY_PROFILE="qwen-image"
modal serve comfyui_modal.py
```

默认 GPU fallback：

```text
L4 → L40S → RTX-PRO-6000
```

覆盖：

```bash
MODAL_GPU=L40S COMFY_PROFILE=wan22 modal serve comfyui_modal.py
```

也可以：

```bash
MODAL_GPU=L4,L40S,RTX-PRO-6000 COMFY_PROFILE=wan22 modal serve comfyui_modal.py
```

## 5. `.env` / Secret

最简单的个人开发方式：

```bash
cp .env.example .env
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

然后编辑 `.env`。支持：

```dotenv
HF_TOKEN=...
CIVITAI_TOKEN=...
GITHUB_TOKEN=...
GEMINI_API_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
QWEN_API_KEY=...
OLLAMA_URL=http://localhost:11434
```

如果没有设置 `MODAL_SECRET_NAME`，`comfyui_modal.py` 会自动用 `modal.Secret.from_dotenv(".env")` 把本地 `.env` 注入：

- CPU 模型同步 Function；
- GPU ComfyUI Function；
- custom node 的 Image build 阶段。

因此 `HF_TOKEN` 可访问 gated/private Hugging Face，`CIVITAI_TOKEN` 用于 Civitai，`GITHUB_TOKEN` 可用于 private custom-node repo。GitHub 建议使用只读、repo-scoped 的 fine-grained token。

`.env` 已加入 `.gitignore`，`.env.example` 只保存占位符。不要把真实 Key 写进 `recipes.py` 或提交到 Git。

### 可选：转成持久 Modal Secret

如果你不想每台开发机都保留 `.env` 注入，可以一次创建：

```bash
modal secret create comfyui-secrets --from-dotenv .env --force
```

然后：

```bash
MODAL_SECRET_NAME=comfyui-secrets \
COMFY_PROFILE=nordy-kontext-views \
modal deploy comfyui_modal.py
```

PowerShell：

```powershell
$env:MODAL_SECRET_NAME="comfyui-secrets"
$env:COMFY_PROFILE="nordy-kontext-views"
modal deploy comfyui_modal.py
```

优先级是：

```text
MODAL_SECRET_NAME 指定的 named Secret
        >
本地 .env
        >
无 Secret
```

如果 `ComfyUI-OllamaGemini` 被选入 Image，运行时会从这些环境变量生成它的 `config.json`，不会把 API Key 写进仓库。

> 原 Notebook 中出现过明文 token。若那些 token 仍有效，建议在对应平台轮换。

## 6. 最常修改的文件：`recipes.py`

### 新模型包

```python
MODEL_PACKS = {
    # ...
    "my-model": {
        "diffusion_models": (
            M("https://huggingface.co/.../model.safetensors"),
        ),
        "text_encoders": (
            M("https://huggingface.co/.../encoder.safetensors"),
        ),
        "vae": (
            M("https://huggingface.co/.../vae.safetensors"),
        ),
    },
}
```

支持显式文件名 / 哈希：

```python
M(
    "https://example.com/download?id=123",
    filename="my_model.safetensors",
    sha256="...",
)
```

压缩包需要自动解压：

```python
M(
    "https://example.com/assets.zip",
    extract=True,
)
```

### 新节点包

```python
NODE_PACKS = {
    # ...
    "my-nodes": (
        N(
            "https://github.com/example/ComfyUI-Example.git",
            requirements=("requirements.txt",),
        ),
    ),
}
```

特殊 pip：

```python
N(
    "https://github.com/example/node.git",
    pip=("some-package", "another-package"),
)
```

特殊安装命令：

```python
N(
    "https://github.com/example/node.git",
    requirements=("requirements.txt",),
    commands=("$PY install.py",),
)
```

固定 branch / tag：

```python
N(
    "https://github.com/example/node.git",
    ref="v1.2.3",
)
```

### 新 Profile

```python
PROFILES = {
    # ...
    "my-profile": Profile(
        model_packs=("my-model",),
        node_packs=("my-nodes",),
        comfy_args=("--preview-method", "auto"),
        description="My workflow",
    ),
}
```

然后：

```bash
modal run comfyui_modal.py --action sync --profile my-profile
COMFY_PROFILE=my-profile modal serve comfyui_modal.py
```

## 7. Wan 两种模式

推荐：

```bash
COMFY_PROFILE=wan22
```

只构建 Wan 常用核心节点，减少 build 时间和依赖冲突。

如果要复刻原 Notebook `wan工作流` cell 的全部**启用**节点：

```bash
COMFY_PROFILE=wan22-notebook-full
```

原 cell 中已经注释掉的 `comfyui_LLM_party` 仍保持禁用。

## 8. 自定义运行参数

```bash
EXTRA_ARGS='--lowvram --preview-method auto' \
COMFY_PROFILE=qwen-image \
modal serve comfyui_modal.py
```

Profile 参数先加载，`EXTRA_ARGS` 再追加。

## 9. Civitai 特殊 URL

原 Notebook 的 `nordy-kontext-views` 中有 Civitai API 下载地址，没有显式文件名。Recipe 保留了原 URL。

如果下载端点返回的名字不适合作为 ComfyUI 文件名，直接在 `recipes.py` 改成：

```python
M(
    "https://civitai.com/api/download/models/...",
    filename="明确的文件名.safetensors",
)
```

无需修改 downloader。

## 10. 为什么不把所有东西塞进 `comfyui_modal.py`

主脚本只负责 Modal：

```text
Modal resources
GPU fallback
Volume
sync function
web_server
```

所有经常变化的内容都在：

```text
recipes.py
```

所有很少变化的机制都在：

```text
comfy_engine.py
```

这使 Notebook 从“执行脚本集合”变成可复现、可组合、可版本控制的 ComfyUI 配方库。

## 开发与验证

项目固定使用 Python 3.12 和 Modal 1.5.4。无需安装第三方测试框架即可运行核心单元测试：

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

GitHub Actions 还会运行 Ruff 静态检查。升级 Modal SDK 时应先核对官方
[`llms.txt`](https://modal.com/llms.txt) 与 Python SDK changelog，再单独提交版本升级。
