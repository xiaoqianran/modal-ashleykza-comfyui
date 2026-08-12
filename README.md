# modal-ashleykza-comfyui

把原来的 ComfyUI Docker / Jupyter Notebook 操作拆成可维护的 **Base Image → Recipe → Sync → Run** 架构。

核心目标：**GPU 只负责 ComfyUI 启动与推理**。模型下载、130 个常用节点、依赖解析都不放在 GPU 冷启动路径里。

## 架构

```text
Ashley ComfyUI Image
        │
        ├── base_nodes.py
        │     固定一点通 130-node 名单 + GitHub clone
        │     + 统一 uv-sync 依赖解析
        │
        ├── recipes.py
        │     MODEL_PACKS   模型资产
        │     NODE_PACKS    仅 Base 没有的 extra nodes
        │     PROFILES      可直接运行的组合
        │
        ▼
   Modal Runtime Image
        │
        ├──────── CPU sync ────────► Modal Volume
        │                            models / lock state
        │
        └──────── GPU run ─────────► ComfyUI :3001
```

### 存储边界

**Image（不可变）**

- `/ComfyUI` 源码、venv、CUDA / torch；
- 一点通 Base Snapshot 的 130 个 custom nodes（GitHub clone）；
- 当前 Profile 少量额外节点；
- 节点 Python 依赖。

**Volume（可变）**

- `/workspace/models`
- `/workspace/input`
- `/workspace/output`
- `/workspace/user`
- `/workspace/custom_nodes`（实验性用户节点）
- `/workspace/logs`
- `/workspace/state/comfy.lock.json`

`/ComfyUI/models` 不被覆盖；`extra_model_paths.yaml` 让 ComfyUI 同时读取 `/workspace/models`。

## Base Nodes：一点通 130-node Snapshot

**默认开启** `COMFY_BASE_NODES=1`。可不写该环境变量；缺省即在 Modal Image build 时构建这 130 个 Base 节点。只有排查问题时才临时设 `COMFY_BASE_NODES=0`。

节点**名单**来自：

```text
https://cnb.cool/SKDZSS90/ComfyUI-yi_dian_tong/-/blob/main/nodes.md
```

CNB git 仓库里**没有** `ComfyUI/custom_nodes`（只有 `nodes.md`）。真正插件在 CNB Docker 镜像里，例如：

```text
docker.cnb.cool/skdzss90/fenxiang/py312_t291_c130:xin-L40g-0811
```

该镜像约 23GiB（CUDA 13 + 模型 + venv），不适合 `COPY --from` 进 Ashley（CUDA 12.8）运行时。镜像 history 显示这些插件本来就是 `cm-cli.sh install` / `git clone` 装上的，所以 Base 安装改为：**按 `nodes.md` 目录名，从 GitHub shallow clone 对应仓库**。URL 从上述镜像（以及旧镜像 `3lian_guan_zhu:0531-v.0.3.39-n120`）的 Dockerfile history 还原；个别仓库已删除时用仍可 clone 的归档/fork。

`base_nodes.py` 保存这 130 个**精确目录名**和 GitHub URL，并作为 Image build 安装脚本（`python base_nodes.py --comfy-root ...`）。`comfyui_modal.py` 先用 `Image.add_local_file(..., copy=True)` 把它拷进镜像，再跑 `build_base_nodes_commands()` 生成的**单行** `run_commands` 步骤。Modal 会把 `run_commands` 包进 Dockerfile `RUN`，**不支持 shell heredoc**，因此不在命令里内嵌大段 Python。Clone 步骤会使用 `GITHUB_TOKEN`（与 extra nodes 相同的 askpass，避免 xtrace 泄露）。

Image build 时：

1. 按 `BASE_NODE_SOURCES` 把 129 个 GitHub 仓库 shallow clone 到 `/ComfyUI/custom_nodes/<nodes.md 目录名>`（`comfyui-manager` 不 clone）；
2. 缺一个 clone 失败就让 Image build 失败，不静默跳过；
3. 删除复制/clone 来的 Manager 目录（改用固定 pip 版 Manager）；
4. 写入 `/opt/comfy-base-nodes.json`；
5. 使用固定版本 `comfy-cli==1.12.0`、`comfyui-manager==4.2.2`；
6. 通过 `comfy node uv-sync` 对现有 custom nodes 做统一依赖解析。

这避免了一个重要错误：`nodes.md` 中的名字是上游安装目录名，**不能假定等于 Comfy Registry ID**，因此不会把这 130 个名字直接传给 `comfy node install`。也不要把整个 CNB 运行时镜像当 Base——只要节点源码，依赖在 Ashley venv 里用 `uv-sync` 解析。

正常 `modal serve` / `modal deploy` 不需要设置 `COMFY_BASE_NODES`。

### 排查时可临时关闭

仅在需要确认问题是否来自 Base 节点时临时关闭（调试用，不是推荐路径）：

```bash
COMFY_BASE_NODES=0 COMFY_PROFILE=qwen-image modal serve comfyui_modal.py
```

## Profiles

当前迁移：

- `base`
- `ltx23`
- `nordy-kontext-views`
- `nordy-clothes`
- `qwen-image`
- `flux-krea`
- `flux-kontext`
- `wan22`
- `wan22-notebook-full`
- `nunchaku`

### Extra Nodes 的原则

130-node Base 已经包含 WanVideoWrapper、KJNodes、VideoHelperSuite、GGUF、Manager、Impact Pack、ControlNet Aux、LayerStyle、Essentials 等大量常用节点。

所以 `recipes.py::NODE_PACKS` **只维护 Base 没有的差异**，例如：

- RunningHub Qwen Image；
- omini-kontext；
- `cg-use-everywhere` / tinyterra；
- OllamaGemini / RES4LYF / Advanced-ControlNet / Curve；
- Nunchaku。

`wan22` 本身不再重复安装 Wan / KJ / VHS / GGUF。

## 1. 安装 Modal

```bash
pip install -U modal
modal setup
```

## 2. 查看 Profile

```bash
modal run comfyui_modal.py --action profiles
```

## 3. CPU 同步模型

Qwen Image：

```bash
modal run comfyui_modal.py --action sync --profile qwen-image
```

Wan 2.2：

```bash
modal run comfyui_modal.py --action sync --profile wan22
```

模型同步不申请 GPU，写入：

```text
/workspace/models/...
/workspace/state/comfy.lock.json
```

同一资产再次同步时，lock 中 URL + size 一致会跳过；Recipe 可填写 `sha256=` 做强校验。

### 下载路由

```text
Hugging Face  → huggingface_hub / hf_xet
                    ↓ fail
                 aria2c

Civitai / HTTP → aria2c
                    ↓
               Modal Volume
```

`huggingface_hub` 固定为 `1.24.0`，并开启 `HF_XET_HIGH_PERFORMANCE=1`。

## 4. 启动 UI / API

临时测试：

```bash
COMFY_PROFILE=qwen-image modal serve comfyui_modal.py
```

持久部署：

```bash
COMFY_PROFILE=qwen-image modal deploy comfyui_modal.py
```

PowerShell：

```powershell
$env:COMFY_PROFILE="qwen-image"
modal serve comfyui_modal.py
```

默认 GPU 偏好（serve / deploy）：**T4 优先**（测试更便宜），然后 L4 / L40S / RTX-PRO-6000：

```text
T4 → L4 → L40S → RTX-PRO-6000
```

需要更大 GPU 时再用 `MODAL_GPU` 覆盖：

```bash
MODAL_GPU=L4 COMFY_PROFILE=wan22 modal serve comfyui_modal.py
```

或：

```bash
MODAL_GPU=L4,L40S,RTX-PRO-6000 COMFY_PROFILE=wan22 modal serve comfyui_modal.py
```

容器空闲约 5 分钟后允许 scale down；模型仍保留在 Volume。

## 5. Secret

不要把真实 token 写进 `recipes.py`。

个人开发：

```bash
cp .env.example .env
```

支持：

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

也可以建立 Modal Secret：

```bash
modal secret create comfyui-secrets --from-dotenv .env --force
```

然后：

```bash
MODAL_SECRET_NAME=comfyui-secrets \
COMFY_PROFILE=qwen-image \
modal deploy comfyui_modal.py
```

优先级：

```text
MODAL_SECRET_NAME > 本地 .env > 无 Secret
```

原 Notebook 曾出现明文 HF / Civitai / Gemini token；如果仍有效，应在对应平台轮换。

## 6. 日常修改：只改 `recipes.py`

### 新模型包

```python
MODEL_PACKS = {
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

显式文件名 / 哈希：

```python
M(
    "https://example.com/download?id=123",
    filename="my_model.safetensors",
    sha256="...",
)
```

### Base 没有的新节点

```python
NODE_PACKS = {
    "my-extra": (
        N(
            "https://github.com/example/ComfyUI-Example.git",
            requirements=("requirements.txt",),
        ),
    ),
}
```

不要把 Base 已有节点重复放到 Profile Node Pack。

### 新 Profile

```python
PROFILES = {
    "my-profile": Profile(
        model_packs=("my-model",),
        node_packs=("my-extra",),
        comfy_args=("--preview-method", "auto"),
        description="My workflow",
    ),
}
```

## 7. 更新 Base Snapshot

Base **不会自动追随** CNB `main` 或 Docker tag。要升级：

1. 检查上游新的 `nodes.md`；
2. 如有需要，从新的 CNB 镜像 history 核对 GitHub URL；
3. 更新 `BASE_NODE_SOURCES`（目录名 + clone URL）；
4. 更新 `BASE_NODES_IMAGE` / snapshot 日期；
5. 跑测试；
6. 重新 `modal serve/deploy`，让 Modal 构建新的 Base layer。

`nodes.md` 名单是固定的；每次 Image build 会 clone 各仓库当时的默认分支 HEAD（`--depth=1`）。若某个上游仓库消失，Image build 会失败而不是少装节点。

## 8. 测试

```bash
python -m py_compile base_nodes.py recipes.py comfy_engine.py comfyui_modal.py tests/test_recipes.py
pytest -q
```

GitHub Actions 也会自动执行相同的基础检查，覆盖：

- Base snapshot 数量 / GitHub URL 映射；
- Profile 引用一致性；
- model destination 冲突；
- extra node 不重复 Base；
- HF Xet / aria2 下载路由；
- GitHub token 不进入 xtrace；
- Notebook 明文 credential 不被迁移。

## 首次 Base Build 的边界

130 个第三方节点是一个很大的兼容性集合。代码现在会**严格失败而不是静默跳过**：源目录缺失或统一依赖解析失败时，Modal Image build 直接报错，不会发布一个“看似成功但少了节点”的半成品。

第一次真正的 Modal Image build 仍然是最终的第三方兼容性验收；通过后，该昂贵 Base layer 会被 Modal Image cache 复用。第三方节点及其模型仍分别受各自许可证约束。
