# 命令行

## hydrate_modal.py

CPU App，只下载模型。

```bash
modal run hydrate_modal.py --catalog z-image
modal run hydrate_modal.py --catalog sam3d
modal run hydrate_modal.py --workflow examples/z-image-base.json
modal run hydrate_modal.py --profile qwen-image
modal run hydrate_modal.py --action resolve --catalog pixal3d
modal run hydrate_modal.py --action profiles
modal run hydrate_modal.py --action outputs
modal run hydrate_modal.py --action repair
```

| 参数 | 说明 |
|---|---|
| `--catalog` | Studio 配方 id，别名到该 JSON 的 workflow / lock |
| `--workflow` | 工作流 JSON / PNG（workflow 模式） |
| `--profile` | 旧 hydrate pack（profile 模式，默认 `base`；Studio 不用这张表） |
| `--lock-out` | 锁文件路径 |
| `--skip-lock-nodes` | GPU 启动时跳过锁内 CNR |
| `--install-nodes` | **无效**（hydrate 不构建 GPU Image）。配方额外包请在 deploy 时设 `COMFY_INSTALL_NODES=1` |
| `--action` | `hydrate`（默认）、`sync` / `workflow-sync`（同 hydrate）、`resolve`、`profiles`、`info`、`outputs`、`repair` |

## comfyui_modal.py

```bash
modal deploy comfyui_modal.py
# 只有改 GPU 端 .py 才用（会挡住 5 秒缩容）：
modal serve comfyui_modal.py
modal run comfyui_modal.py
```

不要用 GPU App 做 hydrate。冒烟默认 **deploy**：命令本身不起 GPU，第一次打到没有 `-dev` 的 `*.modal.run` 才起卡。测完不必 `modal app stop`。

## studio

```bash
python -m studio
./open-studio.sh
open-studio.bat
python -m studio --no-browser
```

Windows：Releases 里只下一个 `Studio.exe`，双击即可。见 [Studio](../guide/studio.md#studio-exe)。

本机 `127.0.0.1:8787`，启动后默认打开浏览器。顶栏配方、GPU、实测见 [模型列表](../guide/models.md) 与 [Studio](../guide/studio.md)。

## 配方脚手架

新 Studio 配方不要手抄四件套，也不要写 `queue_*.py`：

```bash
python3 -m recipe_scaffold path/to/official.json --id your-recipe --title "显示名" --kind t2i
python3 -m recipe_scaffold path/to/official.json --id your-recipe --title "显示名" --kind i23d --write
python3 -m benchmarks --write
```

`--write` 写出 `examples/*.json`、锁、`catalog/<id>.json`。锁里有 `unresolved` 时退出码 2，必须手补 URL / `MODEL_DIRS`。`--write-overlay` 会往 `benchmarks/models.json` 追加一条 `pending`。

`mode=graph`、T4、以及未在 `catalog.gates.NON_L40S_DEFAULT_GPU_IDS` 里的 PRO-6000 测试默认会被拒绝。

## 通用排队

```bash
python3 -m workflow_queue --inspect --workflow examples/z-image-base.json
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/z-image-base.json --prompt "a celadon teapot"
python3 -m workflow_queue --base-url https://<your>.modal.run \
  --workflow examples/triposplat-image-to-gaussian-splat.json \
  --enable-glb --images photo.png --out artifacts/triposplat
```

把官方 UI JSON 交给正在跑的 ComfyUI 做 `graphToPrompt()`，再 `POST /prompt`。TripoSplat 官方模板把 mesh/GLB 设成 bypass，加 `--enable-glb`。见 [工作流与锁文件](../guide/workflows.md)。`scripts/queue_ltx25.py` 仍要保留（Ashley 0.32.0 缺官方节点）。

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
