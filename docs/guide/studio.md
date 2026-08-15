# Studio（本地配方控制面）

引擎（hydrate / Volume / GPU ComfyUI）保持不动。Studio 是本机 App：读 `catalog/*.json` 这份**配方契约**，画出该工作流的表单（提示词、尺寸、上传图），再把任务交给已经在跑的 ComfyUI。

打开后**默认选中 Z-Image**。顶栏配方下拉来自 `catalog/*.json`：图生出现上传框，文生出现提示词。换配方不会改 `comfy_engine.py`。

密钥只写在本机 `.studio.env`（已 gitignore）。页面只绑 `127.0.0.1`。

## Windows：一个 exe {: #studio-exe }

不装 Python 也可以。到 [Releases](https://github.com/xiaoqianran/modal-ashleykza-comfyui/releases) 只下载 `Studio.exe`，双击即可。会打开 [http://127.0.0.1:8787](http://127.0.0.1:8787)。不要再解一堆目录，旁边也不需要 `python/`、`app/`。

第一次运行会把运行时写到 `%LOCALAPPDATA%\ComfyStudio`。下载目录里始终只有这一个 exe。图画在 Modal 云上。

还需要：

- 本机联网、Modal 账号、Hugging Face token
- 走代理：设 `HTTPS_PROXY` / `ALL_PROXY`（内置 Modal 带 `api-proxy-support`）；不要代理就设 `MODAL_DISABLE_API_PROXY=1`
- workflow 模式需要本机 Chrome 或 Edge（`graphToPrompt`）。`mode=graph` 的 Z-Image / Z-Image-Turbo 不需要
- 未签名，SmartScreen 可能提示「Windows 已保护你的电脑」，选「更多信息」→「仍要运行」

密钥写在 `%LOCALAPPDATA%\ComfyStudio\runtime\app\.studio.env`，不会上传 Git。生成结束后默认停残留 GPU 容器（已部署的 App 留着）。

发版：打 `studio-v*` 标签，或在 Actions 里手动跑 **Studio Windows** 并勾选 publish。

已经有 Python 的机器仍可用下面的命令或 `open-studio.bat`。

## 启动

```bash
python -m studio
```

Windows 双击仓库根目录 `open-studio.bat`；macOS / Linux 用 `./open-studio.sh`。启动后会打开浏览器 [http://127.0.0.1:8787](http://127.0.0.1:8787)。不要浏览器：`python -m studio --no-browser`。没有 Python 时用 [Windows：一个 exe](#studio-exe)。

完整 GPU / 权重 / 实测见 [模型列表](models.md)。打开后**默认选中 Z-Image**。顶栏「配方」下拉来自 `catalog/*.json`：

--8<-- "guide/_generated_studio_recipes.md"

换配方只会换表单和允许的卡，不会改引擎代码。`python3 -m benchmarks --write` 会重写上面这张表。

1. 填 Modal token（或留空，沿用 `modal setup` 的 CLI 登录）和 `HF_TOKEN`，保存。
2. 确认顶栏配方，默认是 **Z-Image**。
3. **准备权重** → 按该配方的 `workflow` 跑 hydrate。
4. **部署 GPU**：默认 `modal deploy`（第一次请求才起卡，空闲 5 秒缩到 0）。测试卡除 FLUX.2 / TRELLIS.2 外一律 **L40S**（不要用 T4）。FLUX.2 约 70GB，L40S 放不下。TRELLIS.2 效果依赖显卡，测试和正式都是 **RTX-PRO-6000**。正式出图在下拉里选 **RTX-PRO-6000**。不会静默升卡。只有改 GPU 端 Python 才设 `STUDIO_GPU_MODE=serve`。
5. 也可以把已经在跑的 `*.modal.run` 贴进「Comfy 地址」。
6. 文生图：提示词一行一条，调步数 / CFG / 尺寸 / 种子。图生配方：拖入图片（可多张，按张排队）。
7. **生成结束后默认停残留 GPU 容器**（不 `modal app stop`，快照还在）。需要接着跑，勾选「任务结束后继续占着 GPU」。不要把 ComfyUI 页开着。

关掉 Studio（Ctrl+C）也会尝试停残留容器，不会卸掉已部署的 App。

## 契约（经得起拷问的模板）

一份新配方 = 脚手架吐出的四个文件，**不要**再写 `queue_*.py`：

```bash
python3 -m recipe_scaffold path/to/official.json \
  --id your-recipe --title "显示名" --kind t2i --write
python3 -m benchmarks --write
```

| 文件 | 作用 |
|---|---|
| `examples/<id>.json` | 官方 UI 工作流 |
| `examples/<id>.lock.json` | hydrate 锁（URL / CNR） |
| `catalog/<id>.json` | Studio 表单 + 绑定 + GPU |
| `benchmarks/models.json` | 同一 `id`：权重、节点、冒烟耗时 |

锁里出现 `unresolved` 就先 `python3 -m manager_catalog` 或 `hydrate --action probe`。仍缺再手补 URL 或把新目录加进 `recipes.MODEL_DIRS`。解析器不猜 HuggingFace 仓库。

`catalog/<id>.json` 的 id 必须等于文件名。打开 Studio 就会出现在配方下拉里。例外写在 `catalog/gates.py`，加载时会拒绝：

| 闸门 | 现在允许的例外 |
|---|---|
| `mode=graph` | 只有 Z-Image / Z-Image-Turbo |
| 测试默认不是 L40S | 只有 FLUX.2 / TRELLIS.2 |
| `scripts/queue_*.py` | 只有 `queue_ltx25.py` |
| 不进 catalog | LTX-2.5 |

扩这些集合必须改 `catalog/gates.py` 并在 PR 里写原因。

两种执行模式，选错会在加载时被拒绝：

| `mode` | 何时用 | 生成时做什么 |
|---|---|---|
| `workflow`（默认，新配方用这个） | 官方 UI JSON 能在当前 Image 里打开 | 运行中的 ComfyUI 做 `graphToPrompt()`，再按 `params.bind` 填 LoadImage / 文本 / sampler |
| `graph` | Image **缺节点**，官方 JSON 会红（现在只有 Z-Image / Z-Image-Turbo） | 使用 catalog 里嵌好的 API prompt，`$prompt` `$seed` 等占位符 |

Z-Image 与 Z-Image-Turbo 必须是 `graph`：当前 Image 没有官方模板里的 `ResolutionSelector` / `SaveImageAdvanced` 以及 subgraph 外壳。内层仍是 core 节点，所以 catalog 里嵌一份兼容 prompt。这不是每个配方都要抄的；脚手架也不会生成 `graph`。

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
