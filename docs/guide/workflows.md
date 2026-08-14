# 工作流与锁文件

GPU 启动前，工作流引用的权重必须已经在 Storage 里。锁文件描述「这份工作流需要哪些文件、从哪下载」。

## 通用适配（不要每个 JSON 写一份脚本）

引擎、输出目录、缩容都是全局的。官方 UI JSON 带 subgraph，不能直接 `POST /prompt`；浏览器点 Queue 时会先跑 `app.graphToPrompt()`。无头跑也用**同一件事**：

```bash
python3 -m workflow_queue --inspect --workflow examples/你的.json
modal run hydrate_modal.py --workflow examples/你的.json
MODAL_GPU=T4 modal serve comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/你的.json \
  --images photo.png \
  --prompt "optional text" \
  --out artifacts/run
```

`--inspect` 不占 GPU，只列出能绑定的 LoadImage / 提示词 / Save* 节点。已经是 API prompt（节点带 `class_type`）则跳过浏览器。UI 图需要本机 Chrome + Playwright，去跑正在服务的 ComfyUI 页。

只有下面这些才需要额外文件，不是每个工作流都要：

| 还要特供 | 原因 |
|---|---|
| 手修 `.lock.json` | 自动 resolve 扫进了用不到的权重 |
| `scripts/queue_ltx25.py` 的 patch | Ashley 0.32.0 缺官方节点 |
| Pixal3D 预构建 wheel | 否则会在 GPU 上编译 natten |
| `catalog/*.json` | 只给 Studio 控制面填表单 |

网页里加载同一份 JSON 再 Queue，本来就不需要这些脚本。

官方模板很多时，先 `python3 -m template_analyzer` 分类，不要每个都手写适配。见 [官方模板分析](templates.md)。

## 生成锁文件

```bash
modal run hydrate_modal.py --action resolve --workflow examples/z-image-base.json
```

默认写出 `examples/z-image-base.lock.json`。`--workflow` 不带 `--action resolve` 时会再下载模型。`custom_nodes` 由 GPU 启动时装到 `/workspace/custom_nodes`，不写进 Image。

解析器只做**确定性绑定**，不为每个 JSON 写适配：

| 自动写入锁 | 不猜 / 记 `unresolved` 或 `warnings` |
|---|---|
| `models[]` 里的 name + directory + http(s) URL | 只有文件名，JSON / Note 里都没有可下载 URL |
| Note / MarkdownNote 里 HuggingFace、Civitai 链接，basename 对得上 widget | 对上了 URL 但看不出 `models/<目录>`（锁里会带上 URL，等人补目录） |
| `cnr_id` + `ver`（版本打架时留一版，优先 semver） | 没有 `cnr_id` 的自定义节点 |
| `?download=true` / `/blob/` 规范化后的同一地址 | 同一目标两个不同 URL 且哈希也对不上 |
| 官方目录：`audio_encoders`、`detection`、`frame_interpolation`、`optical_flow`、`model_patches` 等 | 未知目录；`api_*` 云端工作流 |

`hydrate` 在 `require_resolved=True` 时遇到 `unresolved` 会失败。`warnings`（例如 CNR 版本冲突选了哪一版）**不**阻止下载。边界说明见 [官方模板分析](templates.md)。

## 锁文件 schema 1

仓库里的 `examples/z-image-base.lock.json` 结构如下：

```json
{
  "schema": 1,
  "workflow": { "name": "z-image-base.json", "sha256": "..." },
  "models": [
    {
      "category": "diffusion_models",
      "filename": "z_image_bf16.safetensors",
      "url": "https://huggingface.co/…/z_image_bf16.safetensors",
      "sha256": null,
      "source": "node:UNETLoader"
    }
  ],
  "custom_nodes": [],
  "unresolved": [],
  "warnings": []
}
```

校验器会拒绝绝对路径、`..`、重复目标、非 HTTP(S) URL、非法 CNR id 以及非 SHA256 哈希。锁文件可以提交 Git；其中不含 token，认证只从 Modal Secret 注入。

手工补全未解析项时，把对象加入 `models` 并删除 `unresolved` 中的对应条目：

```json
{
  "category": "checkpoints",
  "filename": "vendor/model.safetensors",
  "url": "https://example.com/model.safetensors",
  "sha256": null,
  "source": "manual"
}
```

hydrate 把锁写到 Volume `.state/launch.json`（GPU 启动前做存在性检查）：

```bash
modal run hydrate_modal.py --workflow examples/z-image-base.json
modal deploy comfyui_modal.py
```

## 仓库示例：Z-Image

| Storage 路径 | 作用 |
|---|---|
| `diffusion_models/z_image_bf16.safetensors` | UNet / DiT |
| `text_encoders/qwen_3_4b.safetensors` | 文本编码器 |
| `vae/ae.safetensors` | VAE |

对应文件：`examples/z-image-base.json` 与 `examples/z-image-base.lock.json`。

官方 UI JSON 里还有 `ResolutionSelector` / `SaveImageAdvanced` 以及 subgraph。Ashley 0.32.0 默认 Image **不含**这些节点。Studio 里 Z-Image 因此用 `mode=graph` 的兼容 prompt；新配方不要再嵌 graph，见 [Studio](studio.md)。无 UI 批量出图仍可用 `scripts/run_z_image_prompts.py`。

## 仓库示例：LTX-2.5 distilled

| 文件 | 作用 |
|---|---|
| `examples/ltx-2.5-t2v-i2v-distilled.json` | 官方 UI 工作流（subgraph，frontend 1.48.7） |
| `examples/ltx-2.5-t2v-i2v-distilled.lock.json` | **手修**锁：去掉 resolve 扫到的无关权重 |

不要对 LTX JSON 盲目 `--action resolve`：自动解析会把 `ViT-B-32.pt`、非 distilled transformer 等写进 `unresolved`，hydrate **不会**用这份不完整结果覆盖已校验通过的手修锁。改了 JSON 就要同步改锁。

`POST /prompt` 不能直接吃这份 UI JSON。网页里点 Queue 会先 `graphToPrompt()`。无 UI 时用 `scripts/queue_ltx25.py`：补 0.32.0 缺的节点、展平 subgraph、修正 widget 槽位、排队、把成片拉到 `artifacts/ltx25`。这不是部署必需步骤。

```bash
modal run hydrate_modal.py --workflow examples/ltx-2.5-t2v-i2v-distilled.json
MODAL_GPU=RTX-PRO-6000 modal serve comfyui_modal.py
python3 scripts/queue_ltx25.py --base-url https://<your>.modal.run --workflow examples/ltx-2.5-t2v-i2v-distilled.json
```

## 仓库示例：TripoSplat 图生 Gaussian Splat

| 文件 | 作用 |
|---|---|
| `examples/triposplat-image-to-gaussian-splat.json` | 官方 UI 工作流（subgraph，frontend 1.44.19） |
| `examples/triposplat-image-to-gaussian-splat.lock.json` | 解析锁：BiRefNet + TripoSplat 权重 |

Ashley 0.32.0 已有核心节点（`TripoSplatConditioning`、`SplatToFile3D`、`SaveGLB` 等），锁里 `custom_nodes` 为空。`background_removal/` 已加入 Storage 目录。官方模板把 `SplatToMesh` / 第二路 `SaveGLB` 设成 bypass；原生输出仍是 `spz` + 已启用的 `SaveGLB`。

`POST /prompt` 不能直接吃这份 UI JSON。无 UI 时用 `scripts/queue_triposplat.py`：展平 subgraph、可选打开 mesh/GLB、排队、把模型拉到 `artifacts/triposplat`。这不是部署必需步骤。显存大约要 48GB，必须**显式** `MODAL_GPU=L40S`（默认是 T4，不会再静默升到贵卡）。跑完立刻停掉 `modal serve`，不要把 L40S 挂着。

```bash
modal run hydrate_modal.py --workflow examples/triposplat-image-to-gaussian-splat.json
MODAL_GPU=L40S modal serve comfyui_modal.py
python3 scripts/queue_triposplat.py --base-url https://<your>.modal.run \
  --workflow examples/triposplat-image-to-gaussian-splat.json \
  --images img1.png img2.png img3.png
```

`--no-glb` 可关掉 mesh 重建（省显存）。空闲 scaledown 默认 5 秒，但 leftover `modal serve` / 开着的 ComfyUI 页会阻止缩容。

## 仓库示例：Pixal3D 图生 GLB

| 文件 | 作用 |
|---|---|
| `examples/pixal3d-image-to-3d.json` | 官方 UI 工作流（[Saganaki22/Pixal3D-ComfyUI](https://github.com/Saganaki22/Pixal3D-ComfyUI)） |
| `examples/pixal3d-image-to-3d.lock.json` | **手修**锁：Pixal3D / DINOv3 / RMBG-2.0 / MoGe + CNR 节点 |

锁里是 Registry id `Pixal3D-ComfyUI@0.2.4` 与 `comfyui-custom-scripts@1.2.5`。GPU 启动时先装预构建 wheel：`natten==0.21.6+torch2110cu128`（[whl.natten.org](https://whl.natten.org/)）和 `flash-attn 2.8.3`（torch 2.11 + cu12）。不要用 PyPI 上的 `natten==0.21.6` sdist，那会在 GPU 上编 CUDA kernel。`cmake` / `ninja-build` 仍留在 Image 里，给 `flex_gemm` / `cumesh` / o-voxel / DRTK 用。Storage 增加了 `Pixal3D/` 与 `geometry_estimation/`。`briaai/RMBG-2.0` 在 Hugging Face 上 gated，hydrate 需要已授权的 `HF_TOKEN`。建议 **L40S**（工作流 `1024_cascade`，约 20–32GB 显存）。

```bash
modal run hydrate_modal.py --workflow examples/pixal3d-image-to-3d.json
COMFY_STARTUP_TIMEOUT_SECONDS=3600 MODAL_GPU=L40S modal serve comfyui_modal.py
python3 scripts/queue_pixal3d.py --base-url https://<your>.modal.run \
  --workflow examples/pixal3d-image-to-3d.json \
  --images gecko.png
```

空闲 scaledown 默认 5 秒；`modal serve` 不关就会一直计费。CUDA 内核装在容器 venv，缩容后下次冷启动会再装一遍。测试请用完即停，不要把 L40S 挂着。

## 仓库示例：FLUX.2 [dev] 文生图

| 文件 | 作用 |
|---|---|
| `examples/flux2-dev-t2i.json` | 官方 UI 工作流 `image_flux2_text_to_image`（subgraph） |
| `examples/flux2-dev-t2i.lock.json` | 解析锁：fp8 mixed DiT + Mistral TE + small decoder VAE |
| `catalog/flux2-dev.json` | Studio 契约：约 71GB，测试和正式都是 **RTX-PRO-6000** |

锁内 `custom_nodes` 为空。`POST /prompt` 不能直接吃这份 UI JSON；无 UI 时用 `python3 -m workflow_queue`。不要用 T4 / L40S。VAE 在 `black-forest-labs/FLUX.2-small-decoder`，hydrate 需要已授权的 `HF_TOKEN`。跑完立刻停掉 `modal serve`。

```bash
modal run hydrate_modal.py --workflow examples/flux2-dev-t2i.json
MODAL_GPU=RTX-PRO-6000 modal serve comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/flux2-dev-t2i.json \
  --prompt "a celadon teapot on wet slate" \
  --out artifacts/flux2-dev
```

## 仓库示例：Qwen-Image-2512 文生图

| 文件 | 作用 |
|---|---|
| `examples/qwen-image-2512.json` | 官方 UI 工作流 `image_qwen_Image_2512`（subgraph） |
| `examples/qwen-image-2512.lock.json` | 解析锁：fp8 DiT + Qwen2.5-VL TE + Lightning LoRA（模板里默认关） |
| `catalog/qwen-image-2512.json` | Studio 契约：约 32GB，测试 **L40S**，正式 **RTX-PRO-6000** |

同样走通用 `workflow_queue`，不要再写 `queue_qwen.py`。

```bash
modal run hydrate_modal.py --workflow examples/qwen-image-2512.json
MODAL_GPU=RTX-PRO-6000 modal serve comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/qwen-image-2512.json \
  --prompt "雨夜霓虹巷口，红风衣，电影感" \
  --out artifacts/qwen-image-2512
```

## 仓库示例：Krea-2 Turbo 文生图

| 文件 | 作用 |
|---|---|
| `examples/krea2-turbo-t2i.json` | 官方 UI 工作流 `image_krea2_turbo_t2i`（subgraph） |
| `examples/krea2-turbo-t2i.lock.json` | 解析锁：fp8 Turbo DiT + Qwen3VL-4B TE + Qwen Image VAE |
| `catalog/krea2-turbo.json` | Studio 契约：约 17GB，测试 **L40S**，正式 **RTX-PRO-6000** |

官方 Turbo **8 步**，prompt enhancement 默认开。锁内 `custom_nodes` 为空。同样走 `python3 -m workflow_queue`，不要再写 `queue_krea.py`。风格 LoRA 在模板里默认关，锁里仍有 `krea2_darkbrush` 一份。跑完立刻停掉 `modal serve`。

2026-08-13 在 **NVIDIA RTX PRO 6000 Blackwell**（96GB，ComfyUI 0.32.0）上同一组 5 条提示词 **5/5 success**，占用约 **17.4GB** 显存：

| # | 提示词（摘要） | 秒数 |
|---:|---|---:|
| 1 | 青瓷壶 | **39.2**（冷加载 + prompt enhance） |
| 2 | 雨夜红风衣 | 19.7 |
| 3 | 梯田日出 | 9.0 |
| 4 | 窗边橘猫 | 8.9 |
| 5 | 青花瓷荔枝汽水 | 17.6 |

稳态大约 **9–20 s/张**（含官方默认的 LLM prompt enhancement；短英文提示更快）。

```bash
modal run hydrate_modal.py --workflow examples/krea2-turbo-t2i.json
MODAL_GPU=RTX-PRO-6000 modal serve comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/krea2-turbo-t2i.json \
  --prompt "a celadon teapot on wet slate" \
  --out artifacts/krea2-turbo
```

## 仓库示例：Z-Image-Turbo 文生图

| 文件 | 作用 |
|---|---|
| `examples/z-image-turbo-t2i.json` | 官方 UI 工作流 `image_z_image_turbo`（subgraph） |
| `examples/z-image-turbo-t2i.lock.json` | 解析锁：Turbo DiT + Qwen3-4B TE + `ae` VAE |
| `catalog/z-image-turbo.json` | Studio 契约：蒸馏 **8 步**、CFG 固定 1，测试 **T4**，正式 **RTX-PRO-6000** |

和 Z-Image 一样，Ashley 0.32.0 打不开官方 subgraph 外壳，Studio 用 `mode=graph`。锁内 `custom_nodes` 为空。官方说能进 16GB；负向走 `ConditioningZeroOut`，表单没有 negative。不要再写 `queue_z_image_turbo.py`。

```bash
modal run hydrate_modal.py --workflow examples/z-image-turbo-t2i.json
MODAL_GPU=T4 modal serve comfyui_modal.py
```

无 UI 时走 Studio 的 graph，或对照 `catalog/z-image-turbo.json` 直接 `POST /prompt`。

## 仓库示例：Ideogram 4 文生图

| 文件 | 作用 |
|---|---|
| `examples/ideogram4-t2i.json` | 官方开源 UI 工作流 `image_ideogram4_t2i`（subgraph；**不是** `api_*` 云端节点） |
| `examples/ideogram4-t2i.lock.json` | **手修**锁：双 DiT fp8 + Qwen3-VL-8B + Gemma4 + Flux2 VAE |
| `catalog/ideogram4.json` | Studio 契约：约 38GB，测试 **L40S**，正式 **RTX-PRO-6000** |

锁内 `custom_nodes` 为空。Gemma4 只写在 MarkdownNote 里、没有 Loader widget，自动 resolve 扫不到，所以手补进锁；改了 JSON 不要用未校验的 resolve 覆盖。没有单独的 negative 字符串，guidance 是非对称 CFG。提示词可用自然语言或结构化 JSON（JSON 对排版和画面内文字更稳）。

Ashley **0.32.0** 可能还没有 `Ideogram4Scheduler` / `DualModelGuider` / `CFGOverride` / CLIP type `ideogram4`。配方按契约加齐，hydrate 与 Studio 表单都能用；生成时如果节点是红的，需要更新 ComfyUI，**不要**为此再写 `queue_ideogram.py`，也不要在本 PR 里升级整份 GPU Image。

```bash
modal run hydrate_modal.py --workflow examples/ideogram4-t2i.json
MODAL_GPU=RTX-PRO-6000 modal serve comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/ideogram4-t2i.json \
  --prompt "a celadon teapot on wet slate" \
  --out artifacts/ideogram4
```

跑完立刻停掉 `modal serve`。不要用 T4。

## 自定义工作流

1. 在本地 ComfyUI 导出 API / workflow JSON（或带嵌入工作流的 PNG）。
2. `resolve` 查看 `unresolved`；缺 URL 就补进 JSON 或锁文件。
3. `hydrate` 写入 Storage。
4. `modal volume ls comfyui-ashleykza-models` 确认 category 与文件名。
5. `modal deploy` 后在 UI 里加载**同一份** JSON。

文件名必须与 Loader 节点里填的字符串完全一致（含扩展名）。

!!! note "UI 里临时拖入的新工作流"
    已经在跑的 GPU 容器事先不知道新 JSON。正确做法是先拿到文件 → hydrate → 再部署或开新容器。GPU 端不会回退到在线安装。

## 无法自动解决的情况

- 工作流只有本地文件名，没有 URL
- custom node 缺少 CNR 元数据且不在 Recipe
- 下载需要网页交互或自定义授权
- 模型名由节点运行时动态计算
- 工作流依赖的 ComfyUI 版本与当前 Image 不兼容
