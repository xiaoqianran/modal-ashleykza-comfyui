# 命令行

## hydrate_modal.py

CPU App，只下载模型。

```bash
modal run hydrate_modal.py --workflow examples/z-image-base.json
modal run hydrate_modal.py --profile qwen-image
modal run hydrate_modal.py --action resolve --workflow workflow.json
modal run hydrate_modal.py --action profiles
modal run hydrate_modal.py --action outputs
modal run hydrate_modal.py --action repair
```

| 参数 | 说明 |
|---|---|
| `--workflow` | 工作流 JSON / PNG（workflow 模式） |
| `--profile` | 配方名（profile 模式，默认 `base`） |
| `--lock-out` | 锁文件路径 |
| `--skip-lock-nodes` | GPU 启动时跳过锁内 CNR |
| `--install-nodes` | **无效**（hydrate 不构建 GPU Image）。配方额外包请在 serve/deploy 时设 `COMFY_INSTALL_NODES=1` |
| `--action` | `hydrate`（默认）、`sync` / `workflow-sync`（同 hydrate）、`resolve`、`profiles`、`info`、`outputs`、`repair` |

## comfyui_modal.py

```bash
modal serve comfyui_modal.py
modal deploy comfyui_modal.py
modal run comfyui_modal.py
```

不要用 GPU App 做 hydrate。

## studio

```bash
python -m studio
./open-studio.sh
open-studio.bat
python -m studio --no-browser
```

Windows：Releases 里只下一个 `Studio.exe`，双击即可。见 [Studio](../guide/studio.md#studio-exe)。

本机 `127.0.0.1:8787`，启动后默认打开浏览器。顶栏选 Z-Image / Z-Image-Turbo / FLUX.2 [dev] / Qwen-Image-2512 / Qwen-Image-2512 Lightning / Krea-2 Turbo / Ideogram 4 / Cosmos3-Nano / Cosmos3-Super / Cosmos3-Super-Text2Image / Cosmos3-Super-Image2Video / Pixal3D / TripoSplat。见 [Studio](../guide/studio.md)。

## 通用排队

```bash
python3 -m workflow_queue --inspect --workflow examples/z-image-base.json
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/z-image-base.json --prompt "a celadon teapot"
```

把官方 UI JSON 交给正在跑的 ComfyUI 做 `graphToPrompt()`，再 `POST /prompt`。见 [工作流与锁文件](../guide/workflows.md)。

## 官方模板分析

```bash
python3 -m template_analyzer --dir /path/to/workflow_templates/templates
```

只读 JSON，不占 GPU。见 [官方模板分析](../guide/templates.md)。

## Volume

```bash
modal volume ls comfyui-ashleykza-models
modal volume get comfyui-ashleykza-workspace /output ./output
```
