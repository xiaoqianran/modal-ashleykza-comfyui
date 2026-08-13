# 实测耗时（参考）

本页汇总 Modal 上跑通的配方**墙钟耗时**与对应 GPU，供后续选型、报价和 Studio 默认值参考。

机器可读数据在仓库根目录 [`benchmarks/timings.json`](https://github.com/xiaoqianran/modal-ashleykza-comfyui/blob/main/benchmarks/timings.json)。有新跑测时更新该 JSON 和本页。

## 共用环境

| 项 | 值 |
|---|---|
| Image | ashleykleynhans/comfyui（cu128，Python 3.12） |
| ComfyUI | **0.32.0** |
| 平台 | Modal（profile `weiranzhiqian`） |
| 计时方式 | `POST /prompt` → `/history` 出现 `success` 的客户端墙钟 |
| 空闲缩容 | **5 秒**（`modal serve` 或开着 ComfyUI 网页会阻止缩容） |

!!! note "怎么读「首张」和「热显存」"
    - **首张**：常含权重装进 VRAM、同卡换模、或容器刚起来；不能代表稳态吞吐。
    - **热显存 / 后续张**：同一 GPU、同一模型、权重已在显存里的稳态速度。
    - Memory snapshot 能省 ComfyUI 进程启动，**不一定**加快「磁盘 → VRAM」的首张加载。

## 总览

| 配方 | 模型 | 推荐 GPU | 显存（观测/估计） | 稳态耗时 | 首张耗时 | 来源 |
|---|---|---|---:|---:|---:|---|
| `flux2-dev` | FLUX.2 [dev] | **RTX-PRO-6000** | ~71 GB | **~15.4 s/张** | ~**144 s** | PR #21，2026-08-13 |
| `qwen-image-2512` | Qwen-Image-2512 | **RTX-PRO-6000** | ~32 GB | **~54 s/张** | ~**78 s** | PR #21，2026-08-13 |
| `triposplat` | TripoSplat | **L40S** | ~48 GB | **30–54 s/张**（视输入） | — | PR #13，2026-08-13 |
| `pixal3d` | Pixal3D | **L40S** | ~20–32 GB | *待补* | — | PR #14 仅验证跑通 |
| `z-image` | Z-Image | **T4** | 轻量 | *待补* | — | 默认配方，尚未正式记时 |

Studio 顶栏配方与上表 `catalog_id` 一一对应。

---

## FLUX.2 [dev] — RTX-PRO-6000

**日期：** 2026-08-13  
**GPU：** NVIDIA RTX PRO 6000 Blackwell Server Edition（96 GB）  
**工作流：** `examples/flux2-dev-t2i.json`（官方 `image_flux2_text_to_image`）  
**条件：** 1024²，**20 步**，turbo LoRA **关**，`graphToPrompt` + `POST /prompt`，5/5 success

| # | 提示词（摘要） | 秒数 | 备注 |
|---:|---|---:|---|
| 1 | 青瓷壶 / celadon teapot | **144.0** | 冷加载 ~70 GB VRAM；ComfyUI execution ≈ 143981 ms |
| 2 | 雨夜红风衣 | 15.35 | 热显存 |
| 3 | 梯田日出 | 15.38 | 热显存 |
| 4 | 窗边橘猫 | 15.38 | 热显存 |
| 5 | 青花瓷荔枝汽水 | 15.34 | 热显存 |

**稳态：** 15.34–15.38 s/张（均值约 **15.36 s**）。

---

## Qwen-Image-2512 — RTX-PRO-6000

**日期：** 2026-08-13（紧接 Flux.2 同卡连跑）  
**GPU：** 同上 RTX-PRO-6000  
**工作流：** `examples/qwen-image-2512.json`（官方 `image_qwen_Image_2512`）  
**条件：** 1328²，**50 步**，Lightning LoRA **关**，5/5 success

| # | 提示词（摘要） | 秒数 | 备注 |
|---:|---|---:|---|
| 1 | 青瓷壶 | **77.59** | 从 Flux.2 切模 + 50 步 |
| 2 | 雨夜红风衣 | 53.99 | 热显存 |
| 3 | 梯田日出 | 53.93 | 热显存 |
| 4 | 窗边橘猫 | 53.89 | 热显存 |
| 5 | 青花瓷荔枝汽水 | 53.84 | 热显存 |

**稳态：** 53.84–53.99 s/张（均值约 **53.9 s**）。

同一组 5 条提示词也用于 Flux.2，便于横向对比。

---

## TripoSplat — L40S

**日期：** 2026-08-13  
**GPU：** NVIDIA **L40S**  
**工作流：** `examples/triposplat-image-to-gaussian-splat.json`  
**输出：** Gaussian Splat（SPZ）+ GLB，3/3 success

| 输入图 | 推理（s） | SPZ | GLB |
|---|---:|---:|---:|
| headphones | **53.7** | 3.0 MB | 39 MB |
| wristwatch | **30.1** | 2.7 MB | 8.8 MB |
| rubber-duck | **32.8** | 2.9 MB | 58 MB |

图生 3D，耗时随物体复杂度和导出体积变化较大。

---

## Pixal3D — L40S

**日期：** 2026-08-13  
**GPU：** L40S  
**工作流：** `examples/pixal3d-image-to-3d.json`（`1024_cascade`）  
**状态：** `gecko.jpg` 跑通并导出 GLB（PR #14），**尚未记录墙钟秒数**。

补测建议：

```bash
modal run hydrate_modal.py --workflow examples/pixal3d-image-to-3d.json
COMFY_STARTUP_TIMEOUT_SECONDS=3600 MODAL_GPU=L40S modal serve comfyui_modal.py
python3 scripts/queue_pixal3d.py --base-url https://<your>.modal.run --images gecko.jpg
```

把终端里的 `seconds` 写回 `benchmarks/timings.json`。

---

## Z-Image — T4

**默认 Studio 配方**，`catalog/z-image.json`：

- GPU：**T4**（也可选 L4 / L40S，未正式对比）
- 默认 **1024²，25 步，CFG 4.0**
- 执行 `mode=graph`（Ashley 0.32.0 无官方 subgraph 节点）

**尚未在本仓记下正式批量耗时。** 可用：

```bash
modal run hydrate_modal.py --workflow examples/z-image-base.json
MODAL_GPU=T4 modal serve comfyui_modal.py
python3 scripts/run_z_image_prompts.py --base-url https://<your>.modal.run
```

产物与 `timings.json` 默认写到 `artifacts/z-image-runs/`。

---

## 复现与更新

1. hydrate 对应 workflow lock  
2. **显式** `MODAL_GPU=…`（贵卡不会从 T4 静默升级）  
3. `modal serve comfyui_modal.py` 或 Studio「启动 GPU」  
4. 批量脚本或 Studio 排队；记下每张 `seconds`  
5. 更新 `benchmarks/timings.json` 与本页表格  
6. **测完停 serve**，避免 5s scaledown 被 leftover 进程挡住

相关 PR：[#13 TripoSplat](https://github.com/xiaoqianran/modal-ashleykza-comfyui/pull/13)、[#14 Pixal3D](https://github.com/xiaoqianran/modal-ashleykza-comfyui/pull/14)、[#21 FLUX.2 + Qwen](https://github.com/xiaoqianran/modal-ashleykza-comfyui/pull/21)。
