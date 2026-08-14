# Studio（本地配方控制面）

引擎（hydrate / Volume / GPU ComfyUI）保持不动。Studio 是本机 App：读 `catalog/*.json` 这份**配方契约**，画出该工作流的表单（提示词、尺寸、上传图），再把任务交给已经在跑的 ComfyUI。

打开后**默认选中 Z-Image**，出现 Z-Image 的配置。换成 Pixal3D / TripoSplat / Cosmos3-Super-Image2Video / Cosmos3-Super-Image2Video-4Step 就换成「上传图片」，换成 FLUX.2 / Qwen-Image-2512 / Qwen-Image-2512 Lightning / Krea-2 Turbo / Z-Image-Turbo / Ideogram 4 / Cosmos3-Nano / Cosmos3-Edge / Cosmos3-Super / Cosmos3-Super-Text2Image / Cosmos3-Super-Text2Image-4Step 仍是提示词。不会改 `comfy_engine.py`。

密钥只写在本机 `.studio.env`（已 gitignore）。页面只绑 `127.0.0.1`。

## Windows：一个 exe {: #studio-exe }

不装 Python 也可以。到 [Releases](https://github.com/xiaoqianran/modal-ashleykza-comfyui/releases) 只下载 `Studio.exe`，双击即可。会打开 [http://127.0.0.1:8787](http://127.0.0.1:8787)。不要再解一堆目录，旁边也不需要 `python/`、`app/`。

第一次运行会把运行时写到 `%LOCALAPPDATA%\ComfyStudio`。下载目录里始终只有这一个 exe。图画在 Modal 云上。

还需要：

- 本机联网、Modal 账号、Hugging Face token
- 走代理：设 `HTTPS_PROXY` / `ALL_PROXY`（内置 Modal 带 `api-proxy-support`）；不要代理就设 `MODAL_DISABLE_API_PROXY=1`
- FLUX.2 / Qwen / Krea-2 / Ideogram 4 / Cosmos3 / Pixal3D / TripoSplat：本机已装 Chrome 或 Edge（Z-Image / Z-Image-Turbo 不需要）
- 未签名，SmartScreen 可能提示「Windows 已保护你的电脑」，选「更多信息」→「仍要运行」

密钥写在 `%LOCALAPPDATA%\ComfyStudio\runtime\app\.studio.env`，不会上传 Git。生成结束后默认停 GPU。

发版：打 `studio-v*` 标签，或在 Actions 里手动跑 **Studio Windows** 并勾选 publish。

已经有 Python 的机器仍可用下面的命令或 `open-studio.bat`。

## 启动

```bash
python -m studio
```

Windows 双击仓库根目录 `open-studio.bat`；macOS / Linux 用 `./open-studio.sh`。启动后会打开浏览器 [http://127.0.0.1:8787](http://127.0.0.1:8787)。不要浏览器：`python -m studio --no-browser`。没有 Python 时用 [Windows：一个 exe](#studio-exe)。

打开后**默认选中 Z-Image**。顶栏「配方」下拉可换成：

| 配方 | 测试默认 | 正式推理 | 输入 |
|---|---|---|---|
| Z-Image | L40S | RTX-PRO-6000 | 提示词 |
| Z-Image-Turbo | L40S | RTX-PRO-6000 | 提示词 |
| FLUX.2 [dev] | RTX-PRO-6000 | RTX-PRO-6000 | 提示词 |
| Qwen-Image-2512 | L40S | RTX-PRO-6000 | 提示词 |
| Qwen-Image-2512 Lightning | L40S | RTX-PRO-6000 | 提示词 |
| Krea-2 Turbo | L40S | RTX-PRO-6000 | 提示词 |
| Ideogram 4 | L40S | RTX-PRO-6000 | 提示词 |
| Cosmos3-Nano | L40S | RTX-PRO-6000 | 提示词（文生视频） |
| Cosmos3-Edge | L40S | RTX-PRO-6000 | 提示词（文生视频） |
| Cosmos3-Super | L40S | RTX-PRO-6000 | 提示词（文生视频） |
| Cosmos3-Super-Text2Image | L40S | RTX-PRO-6000 | 提示词 |
| Cosmos3-Super-Text2Image-4Step | L40S | RTX-PRO-6000 | 提示词（蒸馏 4 步） |
| Cosmos3-Super-Image2Video | L40S | RTX-PRO-6000 | 上传图 + 提示词 |
| Cosmos3-Super-Image2Video-4Step | L40S | RTX-PRO-6000 | 上传图 + 提示词（蒸馏 4 步） |
| Pixal3D | L40S | RTX-PRO-6000 | 上传图 |
| TripoSplat | L40S | RTX-PRO-6000 | 上传图 |

换配方只会换表单和允许的卡，不会改引擎代码。

1. 填 Modal token（或留空，沿用 `modal setup` 的 CLI 登录）和 `HF_TOKEN`，保存。
2. 确认顶栏配方，默认是 **Z-Image**。
3. **准备权重** → 按该配方的 `workflow` 跑 hydrate。
4. **启动 GPU**：默认用配方里的测试卡。除 FLUX.2 外一律 **L40S**（不要用 T4）。FLUX.2 约 70GB，L40S 放不下，测试也只能是 **RTX-PRO-6000**。正式出图在下拉里选 **RTX-PRO-6000**。不会静默升卡。
5. 也可以把已经在跑的 `*.modal.run` 贴进「Comfy 地址」。
6. 文生图：提示词一行一条，调步数 / CFG / 尺寸 / 种子。图生配方：拖入图片（可多张，按张排队）。
7. **生成结束后默认停止 GPU**。需要接着跑，勾选「任务结束后继续占着 GPU」。

关掉 Studio（Ctrl+C）也会尝试停掉它拉起的 serve。

## 契约（经得起拷问的模板）

一份新配方 = 三个文件，**不要**再写 `queue_*.py`：

| 文件 | 作用 |
|---|---|
| `examples/<id>.json` | 官方 UI 工作流 |
| `examples/<id>.lock.json` | hydrate 锁（URL / CNR） |
| `catalog/<id>.json` | Studio 表单 + 绑定 + GPU |

`catalog/<id>.json` 的 id 必须等于文件名。打开 Studio 就会出现在配方下拉里。

两种执行模式，选错会在加载时被拒绝：

| `mode` | 何时用 | 生成时做什么 |
|---|---|---|
| `workflow`（默认，新配方用这个） | 官方 UI JSON 能在当前 Image 里打开 | 运行中的 ComfyUI 做 `graphToPrompt()`，再按 `params.bind` 填 LoadImage / 文本 / sampler |
| `graph` | Image **缺节点**，官方 JSON 会红（现在只有 Z-Image / Z-Image-Turbo） | 使用 catalog 里嵌好的 API prompt，`$prompt` `$seed` 等占位符 |

Z-Image 与 Z-Image-Turbo 必须是 `graph`：Ashley 0.32.0 没有官方模板里的 `ResolutionSelector` / `SaveImageAdvanced` 以及 subgraph 外壳。内层仍是 core 节点，所以 catalog 里嵌一份兼容 prompt。这不是每个配方都要抄的。

浏览器拿不到 `graph` 字段（`public_catalog` 会剥掉），避免把整份 prompt 泄漏到前端。

### 最小文生图（对照 `catalog/z-image.json`）

```json
{
  "schema": 1,
  "id": "z-image",
  "title": "Z-Image",
  "summary": "文生图。",
  "kind": "t2i",
  "mode": "graph",
  "workflow": "examples/z-image-base.json",
  "lock": "examples/z-image-base.lock.json",
  "gpu": "L40S",
  "gpu_inference": "RTX-PRO-6000",
  "gpu_choices": ["L40S", "RTX-PRO-6000"],
  "params": [
    {"id": "prompt", "type": "text", "bind": "prompt", "title": "提示词", "required": true},
    {"id": "seed", "type": "int", "bind": "seed", "title": "种子", "default": -1, "minimum": -1}
  ]
}
```

`mode=graph` 时还要有 `graph` 对象。新配方不要抄 graph，用下面这份。

### 最小图生（对照 `catalog/pixal3d.json`）

```json
{
  "schema": 1,
  "id": "your-recipe",
  "title": "显示名",
  "summary": "一句话。写清 GPU。",
  "kind": "i23d",
  "mode": "workflow",
  "workflow": "examples/your.json",
  "lock": "examples/your.lock.json",
  "gpu": "L40S",
  "gpu_inference": "RTX-PRO-6000",
  "gpu_choices": ["L40S", "RTX-PRO-6000"],
  "params": [
    {
      "id": "image",
      "type": "image",
      "bind": "image",
      "title": "输入图",
      "required": true
    }
  ]
}
```

允许的 `params.type`：`text` / `int` / `float` / `image`。  
允许的 `bind`：`prompt` `negative` `seed` `steps` `cfg` `width` `height` `image` `filename_prefix`。  
`type=image` 必须 `bind=image`。多张图 = 多个任务，不是塞进同一个 graph。

不要做的：

- 为每个 JSON 写 Python 适配器
- 在 catalog 里编造 HuggingFace 地址（那是锁文件 / resolver 的事）
- 给图生配方默认 T4（测试一律 L40S）
- 测试默认用 RTX-PRO-6000（能放下显存就用 L40S；正式推理才写 `gpu_inference`）
- 把 `graph` 抄到每个新配方上

`workflow` / `lock` 必须是仓库内相对路径，不能 `..`。

CLI 批量出图仍可用（同一份 Z-Image 契约）：

```bash
python3 scripts/run_z_image_prompts.py --base-url https://<your>.modal.run
```

图生配方在无 UI 时走通用适配：

```bash
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/pixal3d-image-to-3d.json \
  --images photo.png
```
