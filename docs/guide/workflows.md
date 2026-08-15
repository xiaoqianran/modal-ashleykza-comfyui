# 工作流与锁文件

GPU 启动前，工作流引用的权重必须已经在 Storage 里。锁文件描述「这份工作流需要哪些文件、从哪下载」。

Studio 全部配方的 GPU / 权重 / 实测见 [模型列表](models.md)。

## 通用适配（不要每个 JSON 写一份脚本）

引擎、输出目录、缩容都是全局的。官方 UI JSON 带 subgraph，不能直接 `POST /prompt`；浏览器点 Queue 时会先跑 `app.graphToPrompt()`。无头跑也用**同一件事**：

```bash
python3 -m workflow_queue --inspect --workflow examples/你的.json
python3 -m manager_catalog --workflow examples/你的.json
modal run hydrate_modal.py --action probe --workflow examples/你的.json
MODAL_GPU=L40S modal deploy comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/你的.json \
  --images photo.png \
  --prompt "optional text" \
  --out artifacts/run
```

`--inspect` 不占 GPU，只列出能绑定的 LoadImage / 提示词 / Save* 节点。已经是 API prompt（节点带 `class_type`）则跳过浏览器。UI 图需要本机 Chrome + Playwright，去跑正在服务的 ComfyUI 页。

只有下面这些才需要额外文件，不是每个工作流都要。清单在 `catalog/gates.py`，单测会卡住新的 `queue_*.py` / `mode=graph`：

| 还要特供 | 原因 | 闸门 |
|---|---|---|
| 手修 `.lock.json` | 自动 resolve 扫进了用不到的权重，或不猜 URL | 脚手架打印 `unresolved` |
| `scripts/queue_ltx25.py` 的 patch | Image 缺官方节点 | `ALLOWED_QUEUE_SCRIPTS` |
| Pixal3D / TRELLIS CUDA wheels | 锁里出现对应 CNR 才装到 Volume | `sparse_3d_runtime`（按 lock node id） |
| SAM 3D comfy-env / pixi | 锁里出现 `ComfyUI-SAM3DObjects` 才装到 Volume | `comfy_env_contract`（钉版本 + 布局）+ `sam3d_runtime` |
| `catalog/*.json` | 只给 Studio 控制面填表单 | 新配方 `mode=workflow` |
| `mode=graph` 内嵌 prompt | 只有 Z-Image / Z-Image-Turbo | `GRAPH_MODE_IDS` |

网页里加载同一份 JSON 再 Queue，本来就不需要这些脚本。

官方模板很多时，先 `python3 -m template_analyzer` 分类，不要每个都手写适配。见 [官方模板分析](templates.md)。

## 生成锁文件

先用脚手架（本机、不占 GPU）：

```bash
python3 -m recipe_scaffold examples/你的.json --id your-recipe --title "显示名" --kind t2i --write
```

有 `unresolved` 就先走 ComfyUI-Manager 探测，不要立刻手写 `queue_*.py`：

```bash
python3 -m manager_catalog --workflow examples/你的.json
modal run hydrate_modal.py --action probe --workflow examples/你的.json
```

这就是网页里上传 JSON 后「Install Missing Custom Nodes」用的同一份 Manager 目录，外加 CPU ComfyUI `--cpu` 对照 `/object_info`。命中才写入锁；仍缺的留 `unresolved` 再手补 URL / `MODEL_DIRS`。不要用 `--action resolve` 覆盖已手修的锁。确认锁齐了再：

```bash
modal run hydrate_modal.py --action resolve --workflow examples/z-image-base.json
```

默认写出 `examples/z-image-base.lock.json`。`--workflow` 不带 `--action resolve` 时会再下载模型。`custom_nodes` 由 GPU 启动时装到 `/workspace/custom_nodes`，不写进 Image。

解析器只做**确定性绑定**，不为每个 JSON 写适配：

| 自动写入锁 | 不猜 / 记 `unresolved` 或 `warnings` |
|---|---|
| `models[]` 里的 name + directory + http(s) URL | 只有文件名，JSON / Note 里都没有可下载 URL |
| Note / MarkdownNote 里 HuggingFace、Civitai 链接，basename 对得上 widget | 对上了 URL 但看不出 `models/<目录>`（锁里会带上 URL，等人补目录） |
| `cnr_id` + `ver`（版本打架时留一版，优先 semver） | 没有 `cnr_id` 的自定义节点（`--action probe` 用 Manager `extension-node-map` 一对一补 GitHub 仓） |
| `?download=true` / `/blob/` 规范化后的同一地址 | 同一目标两个不同 URL 且哈希也对不上 |
| 官方目录：`audio_encoders`、`detection`、`frame_interpolation`、`optical_flow`、`model_patches` 等 | 未知目录；`api_*` 云端工作流 |
| Manager `model-list.json` 里文件名唯一、目录已知 | 文件名对应两个 URL，或 `save_path` 不是已知 `models/` 目录 |

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
MODAL_GPU=RTX-PRO-6000 modal deploy comfyui_modal.py
python3 scripts/queue_ltx25.py --base-url https://<your>.modal.run --workflow examples/ltx-2.5-t2v-i2v-distilled.json
```

## 仓库示例：TripoSplat 图生 Gaussian Splat

| 文件 | 作用 |
|---|---|
| `examples/triposplat-image-to-gaussian-splat.json` | 官方 UI 工作流（subgraph，frontend 1.44.19） |
| `examples/triposplat-image-to-gaussian-splat.lock.json` | 解析锁：BiRefNet + TripoSplat 权重 |

Ashley 0.32.0 已有核心节点（`TripoSplatConditioning`、`SplatToFile3D`、`SaveGLB` 等），锁里 `custom_nodes` 为空。`background_removal/` 已加入 Storage 目录。官方模板把 `SplatToMesh` / 第二路 `SaveGLB` 设成 bypass；原生输出仍是 `spz` + 已启用的 `SaveGLB`。

`POST /prompt` 不能直接吃这份 UI JSON。无 UI 时用 `python3 -m workflow_queue --enable-glb`：展平 subgraph、打开被 bypass 的 mesh/GLB、排队、把模型拉到 `--out`。这不是部署必需步骤。显存大约要 48GB，必须**显式** `MODAL_GPU=L40S`（不要用 T4）。队列结束后不要开着 ComfyUI 页；空闲 5 秒缩容。不要把 L40S 挂着。

```bash
modal run hydrate_modal.py --workflow examples/triposplat-image-to-gaussian-splat.json
MODAL_GPU=L40S modal deploy comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/triposplat-image-to-gaussian-splat.json \
  --enable-glb \
  --images img1.png img2.png img3.png \
  --out artifacts/triposplat
```

`--no-glb` 可关掉 mesh 重建（省显存）。空闲 scaledown 默认 5 秒，但 leftover `modal serve` / 开着的 ComfyUI 页会阻止缩容。

## 仓库示例：Pixal3D 图生 GLB

| 文件 | 作用 |
|---|---|
| `examples/pixal3d-image-to-3d.json` | 官方 UI 工作流（[Saganaki22/Pixal3D-ComfyUI](https://github.com/Saganaki22/Pixal3D-ComfyUI)） |
| `examples/pixal3d-image-to-3d.lock.json` | **手修**锁：Pixal3D / DINOv3 / RMBG-2.0 / MoGe + CNR 节点 |

锁里是 Registry id `Pixal3D-ComfyUI@0.2.4` 与 `comfyui-custom-scripts@1.2.5`。GPU 启动时先装预构建 wheel：`natten==0.21.6+torch2110cu128`（[whl.natten.org](https://whl.natten.org/)）、`flash-attn 2.8.3`，以及 `flex_gemm` / `cumesh` / o-voxel / DRTK（[PozzettiAndrea/cuda-wheels](https://github.com/PozzettiAndrea/cuda-wheels) 的 cu128+torch2.11+cp312）。不要用 PyPI 上的 `natten==0.21.6` sdist，也不要在 GPU 上编 CUDA。Storage 增加了 `Pixal3D/` 与 `geometry_estimation/`。`briaai/RMBG-2.0` 在 Hugging Face 上 gated，hydrate 需要已授权的 `HF_TOKEN`。建议 **L40S**（工作流 `1024_cascade`，约 20–32GB 显存）。

```bash
modal run hydrate_modal.py --workflow examples/pixal3d-image-to-3d.json
MODAL_GPU=L40S modal deploy comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/pixal3d-image-to-3d.json \
  --images gecko.png \
  --out artifacts/pixal3d
```

空闲 scaledown 默认 5 秒。用 `modal deploy` 冒烟；`modal serve` 不关就会一直计费。CUDA wheels 装在 workspace Volume 的 `/workspace/.python/sparse-3d`（wheel 缓存在 `/workspace/.python/wheels`），容器 venv 只放一个 `.pth` 指针。缩容后下次冷启动复用 Volume site，不会再 uv pip / 下载。队列结束即停，不要把 L40S 挂着。

## 仓库示例：Hunyuan3D 2.1 图生 GLB

| 文件 | 作用 |
|---|---|
| `examples/hunyuan3d-2.1-image-to-3d.json` | 官方模板 `3d_hunyuan3d-v2.1`（ComfyUI 核心节点） |
| `examples/hunyuan3d-2.1-image-to-3d.lock.json` | 解析锁：`checkpoints/hunyuan_3d_v2.1.safetensors`（约 4.9GB） |
| `catalog/hunyuan3d-2.1.json` | Studio 契约：图生几何 GLB，测试 **L40S** |

锁内 `custom_nodes` 为空。不要用 Partner/API 的 `api_hunyuan3d_*`，也不要 visualbruno 的 PBR paint（要编 rasterizer）。无 UI 时用 `python3 -m workflow_queue`。建议 **L40S**。不要用 T4。

```bash
modal run hydrate_modal.py --workflow examples/hunyuan3d-2.1-image-to-3d.json
MODAL_GPU=L40S modal deploy comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/hunyuan3d-2.1-image-to-3d.json \
  --images photo.png \
  --out artifacts/hunyuan3d-2.1
```

## 仓库示例：TRELLIS.2 图生 GLB

| 文件 | 作用 |
|---|---|
| `examples/trellis2-image-to-3d.json` | visualbruno `MeshOnly.json`，输入改成核心 `LoadImage` |
| `examples/trellis2-image-to-3d.lock.json` | **手修**锁：`microsoft/TRELLIS.2-4B` + `TRELLIS-image-large` ss_dec + DINOv3（visualbruno 镜像） |
| `catalog/trellis2.json` | Studio 契约：图生几何 GLB，测试和正式都是 **RTX-PRO-6000** |

锁里是 GitHub 节点 `ComfyUI-Trellis2@main`（[visualbruno/ComfyUI-Trellis2](https://github.com/visualbruno/ComfyUI-Trellis2)）。`Trellis2LoadModel` 不走 `extra_model_paths`，GPU 启动时把 `/ComfyUI/models/microsoft` 与 `facebook` symlink 到 Volume。`flex_gemm` / `cumesh` / o-voxel 装 [PozzettiAndrea/cuda-wheels](https://github.com/PozzettiAndrea/cuda-wheels) 的 `cu128torch2.11-cp312` Linux wheel（Ashley 是 Python 3.12；visualbruno 仓库里 Torch2110 Linux 只有 cp313，对不上），同样落到 workspace Volume 的 `.python/sparse-3d`。**DRTK / natten / Pixal3D requirements 只在当前锁是 Pixal3D 时才装**，Volume 上残留的 Pixal3D 目录不会拖进 TRELLIS.2。不要在 GPU 上编 CUDA。MeshOnly 关了 `use_reconviagen`，不要下 vggt。核心 `LoadImage` 是 RGB，所以 `Trellis2PreProcessImage` 打开 `remove_background`（rembg 需要 `onnxruntime`，GPU 启动时补装）。attention 用 **sdpa**（PRO-6000 / Blackwell 不要 flash_attn）。PBR 贴图（`MeshWithTexturing`）留作后续。效果依赖显卡，测试和正式都是 **RTX-PRO-6000**，不要用 T4 / L40S。

```bash
modal run hydrate_modal.py --workflow examples/trellis2-image-to-3d.json
MODAL_GPU=RTX-PRO-6000 modal deploy comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/trellis2-image-to-3d.json \
  --images photo.png \
  --out artifacts/trellis2
```

空闲 scaledown 默认 5 秒。用 `modal deploy` 冒烟；`modal serve` 不关就会一直计费。队列结束即停。

## 仓库示例：SAM 3D Objects 图生 GLB

| 文件 | 作用 |
|---|---|
| `examples/sam3d-image-to-3d.json` | 官方 UI 工作流 `full_generation.json`（[PozzettiAndrea/ComfyUI-SAM3DObjects](https://github.com/PozzettiAndrea/ComfyUI-SAM3DObjects)） |
| `examples/sam3d-image-to-3d.lock.json` | **手修**锁：`apozz/sam-3d-objects-safetensors` → `sam3dobjects/` |
| `catalog/sam3d.json` | Studio 契约：图生带贴图 GLB，测试 **L40S** |

锁里是 GitHub 节点 `ComfyUI-SAM3DObjects@main`。`LoadSAM3DModel` 读 `sam3dobjects/`。隔离协议钉在 `comfy_env_contract.py`：只认 `comfy-env==0.3.89` 和 `/.pixi/envs/<name>` 布局，版本或源码对不上就启动失败，不准追 PyPI latest。官方 `comfy-env-root.toml` 里的 GeometryPack / Multiband **不装**。不要写 `queue_*.py`。官方模板走 InvertMask，**透明底 PNG** 更好。冷启动把 `COMFY_STARTUP_TIMEOUT_SECONDS` 提到 3600。`graphToPrompt` 若没换掉默认图，本地用 `/object_info` 转 API。建议 **L40S**。不要用 T4。

```bash
modal run hydrate_modal.py --catalog sam3d
COMFY_STARTUP_TIMEOUT_SECONDS=3600 MODAL_GPU=L40S modal deploy comfyui_modal.py
python3 -m workflow_queue --base-url https://<workspace>--comfyui-ashleykza-cu128-ui-ui.modal.run \
  --workflow examples/sam3d-image-to-3d.json \
  --images photo.png \
  --out artifacts/sam3d
```

空闲 scaledown 默认 5 秒。用 `modal deploy` 冒烟；`modal serve` 不关就会一直计费。队列结束即停，不要 `modal app stop`。

## 仓库示例：FLUX.2 [dev] 文生图

| 文件 | 作用 |
|---|---|
| `examples/flux2-dev-t2i.json` | 官方 UI 工作流 `image_flux2_text_to_image`（subgraph） |
| `examples/flux2-dev-t2i.lock.json` | 解析锁：fp8 mixed DiT + Mistral TE + small decoder VAE |
| `catalog/flux2-dev.json` | Studio 契约：约 71GB，测试和正式都是 **RTX-PRO-6000** |

锁内 `custom_nodes` 为空。`POST /prompt` 不能直接吃这份 UI JSON；无 UI 时用 `python3 -m workflow_queue`。不要用 T4 / L40S。VAE 在 `black-forest-labs/FLUX.2-small-decoder`，hydrate 需要已授权的 `HF_TOKEN`。队列结束后不要开着 ComfyUI 页；空闲 5 秒缩容。

```bash
modal run hydrate_modal.py --workflow examples/flux2-dev-t2i.json
MODAL_GPU=RTX-PRO-6000 modal deploy comfyui_modal.py
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
MODAL_GPU=RTX-PRO-6000 modal deploy comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/qwen-image-2512.json \
  --prompt "雨夜霓虹巷口，红风衣，电影感" \
  --out artifacts/qwen-image-2512
```

## 仓库示例：Qwen-Image-2512 Lightning（8 步）

| 文件 | 作用 |
|---|---|
| `examples/qwen-image-2512-lightning.json` | 官方 `image_qwen_Image_2512`，打开 LightX2V **8 步** LoRA |
| `examples/qwen-image-2512-lightning.lock.json` | 与 50 步配方同一套 fp8 底模，LoRA 换成 8steps |
| `catalog/qwen-image-2512-lightning.json` | Studio 契约：8 步、CFG 1，测试 **L40S**，正式 **RTX-PRO-6000** |

50 步那份慢，是因为官方模板把 Lightning 默认关着。4 步更快但文字/人像更容易糊；2 步 Wuli Turbo 官方自己写了「牺牲画质」。LightX2V 给 2512 的蒸馏默认就是 **8 步**，速度大约是 50 步的 1/6，画质更接近原版。CFG 固定 1，没有负向。同样走 `python3 -m workflow_queue`，不要再写 `queue_qwen.py`。

```bash
modal run hydrate_modal.py --workflow examples/qwen-image-2512-lightning.json
MODAL_GPU=L40S modal deploy comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/qwen-image-2512-lightning.json \
  --prompt "雨夜霓虹巷口，红风衣，电影感" \
  --out artifacts/qwen-image-2512-lightning
```

## 仓库示例：Krea-2 Turbo 文生图

| 文件 | 作用 |
|---|---|
| `examples/krea2-turbo-t2i.json` | 官方 UI 工作流 `image_krea2_turbo_t2i`（subgraph） |
| `examples/krea2-turbo-t2i.lock.json` | 解析锁：fp8 Turbo DiT + Qwen3VL-4B TE + Qwen Image VAE |
| `catalog/krea2-turbo.json` | Studio 契约：约 17GB，测试 **L40S**，正式 **RTX-PRO-6000** |

官方 Turbo **8 步**，prompt enhancement 默认开。锁内 `custom_nodes` 为空。同样走 `python3 -m workflow_queue`，不要再写 `queue_krea.py`。风格 LoRA 在模板里默认关，锁里仍有 `krea2_darkbrush` 一份。队列结束后不要开着 ComfyUI 页；空闲 5 秒缩容。

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
MODAL_GPU=RTX-PRO-6000 modal deploy comfyui_modal.py
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
| `catalog/z-image-turbo.json` | Studio 契约：蒸馏 **8 步**、CFG 固定 1，测试 **L40S**，正式 **RTX-PRO-6000** |

和 Z-Image 一样，Ashley 0.32.0 打不开官方 subgraph 外壳，Studio 用 `mode=graph`。锁内 `custom_nodes` 为空。官方说能进 16GB；负向走 `ConditioningZeroOut`，表单没有 negative。不要再写 `queue_z_image_turbo.py`。

```bash
modal run hydrate_modal.py --workflow examples/z-image-turbo-t2i.json
MODAL_GPU=L40S modal deploy comfyui_modal.py
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
MODAL_GPU=RTX-PRO-6000 modal deploy comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/ideogram4-t2i.json \
  --prompt "a celadon teapot on wet slate" \
  --out artifacts/ideogram4
```

队列结束后不要开着 ComfyUI 页；空闲 5 秒缩容。不要用 T4。

## 仓库示例：NVIDIA Cosmos 3

Comfy 核心还没有 Cosmos 3 原生节点（[Comfy-Org#14228](https://github.com/Comfy-Org/ComfyUI/issues/14228) 仍 open）。七份配方走 [RyukoMatoiFan/ComfyUI-Cosmos3](https://github.com/RyukoMatoiFan/ComfyUI-Cosmos3)（GitHub 自定义节点，GPU 启动时装到 Volume）。64B bf16 大约 120GB 权重、240GB 主机内存，单卡 RTX-PRO-6000 也放不下；锁里的 transformer 换成 [AkaneTendo25/Cosmos3-ConvRot](https://huggingface.co/AkaneTendo25/Cosmos3-ConvRot) **int4**，Super 系列再打开 `split_reasoner`（官方 4-step 示例没拆，本仓库为省主机内存仍拆）。

ConvRot **没有** Super-Text2Image / Super-Text2Image-4Step 专用 int4。`cosmos3-super-text2image` 用同架构的 Super int4 做 **1 帧**文生图（VAE / tokenizer 仍来自 `nvidia/Cosmos3-Super`）。`cosmos3-super-text2image-4step` 同样权宜：和 I2V-4Step **共用** `Cosmos3-Super-Image2Video-4Step` int4 做 1 帧（官方 T2I-4Step bf16 约 120GB，VAE/tokenizer 与 I2V-4Step 相同）。4-step 配方是 DMD2 蒸馏：`euler` + CFG **1.0** + `distilled_4step`（改步数也会被日程忽略）。Super 系列 int4 主机内存大约 63GB（权重约 47GB）；动态 VRAM 下采样显存大约 8GB，L40S 的 48GB 显存放得下，但主机内存比 Nano / Edge 紧。Nano int4 大约 12GB 权重。Edge 是 4B Nemotron-dense，int4 约 3GB，**不** split；提示词建议 JSON `{"temporal_caption": "..."}`。

| 文件 | 作用 |
|---|---|
| `examples/cosmos3-nano-t2v.json` | Nano 文生视频（832×480 / 93 帧 / 24fps） |
| `examples/cosmos3-nano-t2v.lock.json` | 手修锁：`models/cosmos3/Cosmos3-Nano/` + Nano int4 transformer |
| `catalog/cosmos3-nano.json` | Studio：`kind=t2v`，测试 **L40S** |
| `examples/cosmos3-edge-t2v.json` | Edge 文生视频（832×480 / 93 帧 / 24fps） |
| `examples/cosmos3-edge-t2v.lock.json` | Edge int4（约 3GB） |
| `catalog/cosmos3-edge.json` | Studio：`kind=t2v` |
| `examples/cosmos3-super-t2v.json` | Super 文生视频 + split_reasoner |
| `examples/cosmos3-super-t2v.lock.json` | Super int4（约 47GB） |
| `catalog/cosmos3-super.json` | Studio：`kind=t2v` |
| `examples/cosmos3-super-text2image.json` | 1 帧文生图，`SaveImage` |
| `examples/cosmos3-super-text2image.lock.json` | 与 Super T2V **同一套**权重 |
| `catalog/cosmos3-super-text2image.json` | Studio：`kind=t2i` |
| `examples/cosmos3-super-text2image-4step.json` | 蒸馏 4 步 1 帧文生图 |
| `examples/cosmos3-super-text2image-4step.lock.json` | 与 I2V-4Step **同一套** int4 |
| `catalog/cosmos3-super-text2image-4step.json` | Studio：`kind=t2i`，步数/CFG 锁死 4 / 1.0 |
| `examples/cosmos3-super-image2video.json` | Super-Image2Video 图生视频（16fps） |
| `examples/cosmos3-super-image2video.lock.json` | I2V int4 |
| `catalog/cosmos3-super-image2video.json` | Studio：`kind=i2v`，要上传图 |
| `examples/cosmos3-super-image2video-4step.json` | I2V 蒸馏 4 步（16fps） |
| `examples/cosmos3-super-image2video-4step.lock.json` | I2V-4Step int4（约 47GB） |
| `catalog/cosmos3-super-image2video-4step.json` | Studio：`kind=i2v`，步数/CFG 锁死 4 / 1.0 |

Storage 增加了 `cosmos3/`。不要对这七份 JSON 盲目 `--action resolve`：Loader 的 `model_dir` 是目录名不是文件，自动解析扫不到权重。改了 JSON 不要用未校验的 resolve 覆盖手修锁。不要再写 `queue_cosmos3.py`。

```bash
modal run hydrate_modal.py --workflow examples/cosmos3-nano-t2v.json
MODAL_GPU=L40S modal deploy comfyui_modal.py
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/cosmos3-nano-t2v.json \
  --prompt "a robotic arm wiping a ceramic plate" \
  --out artifacts/cosmos3-nano
```

图生视频把 `--images first.png` 交给 `examples/cosmos3-super-image2video.json` 或 `examples/cosmos3-super-image2video-4step.json`。4-step 文生图用 `examples/cosmos3-super-text2image-4step.json`（hydrate 一次 I2V-4Step 即可，两份锁同一目录）。队列结束后不要开着 ComfyUI 页；空闲 5 秒缩容。不要用 T4。

## 自定义工作流

1. 在本地 ComfyUI 导出 API / workflow JSON（或带嵌入工作流的 PNG）。
2. `python3 -m manager_catalog` 或 `hydrate --action probe`：用 ComfyUI-Manager 目录补锁，CPU 列出还缺的节点 / 文件。
3. 仍有 `unresolved` 就手补 URL 或 `MODEL_DIRS`；不要猜 HuggingFace 仓库。
4. `hydrate` 写入 Storage（锁已齐才会写 `launch.json`）。
5. `modal volume ls comfyui-ashleykza-models` 确认 category 与文件名。
6. `modal deploy` 后在 UI 里加载**同一份** JSON。

文件名必须与 Loader 节点里填的字符串完全一致（含扩展名）。

!!! note "UI 里临时拖入的新工作流"
    已经在跑的 GPU 容器事先不知道新 JSON。正确做法是先拿到文件 → hydrate → 再部署或开新容器。GPU 端不会回退到在线安装。

## 无法自动解决的情况

- 工作流只有本地文件名，Manager `model-list.json` 里也没有唯一 URL（这是常态；探测**不能保证**下到权重）
- custom node 的 `class_type` 在 Manager 表里对应两个 GitHub 仓，或根本不在表里
- 下载需要网页交互或自定义授权
- 模型名由节点运行时动态计算
- 工作流依赖的 ComfyUI 版本与当前 Image 不兼容
- CUDA 专用节点在 CPU `--cpu` 上 import 失败（锁里已有仓则等 GPU 启动再装）
