# modal-ashleykza-comfyui

在 Modal 上跑 ComfyUI。两种启动方式。

**文档：** [https://xiaoqianran.github.io/modal-ashleykza-comfyui/](https://xiaoqianran.github.io/modal-ashleykza-comfyui/)  
**图库：** [https://xiaoqianran.github.io/modal-ashleykza-comfyui/gallery/](https://xiaoqianran.github.io/modal-ashleykza-comfyui/gallery/)


```bash
python -m pip install -U modal
modal setup
cp .env.example .env
modal secret create comfyui-creds --from-dotenv .env --force
```

## 两种启动方式

**1. 工作流 JSON** — 解析 model 和插件；下载模型；锁写到 Volume。GPU Image 不随工作流变化：

```bash
modal run hydrate_modal.py --workflow examples/z-image-base.json
modal serve comfyui_modal.py
```

**2. Profile** — 按 `recipes.py` 拉模型包（配方额外插件默认不装）：

```bash
modal run hydrate_modal.py --profile qwen-image
modal serve comfyui_modal.py
```

130 个上游 GitHub 节点默认不开。需要时：`COMFY_BASE_NODES=1`。配方额外包：`COMFY_INSTALL_NODES=1`（会改 Image）。关掉锁内节点：hydrate 时 `--skip-lock-nodes`。

空闲 **5 秒** 缩掉 GPU（还要求没有 `modal serve` / 浏览器 WebSocket 保活）。默认 GPU 是 **L40S**，不要用 T4。贵卡必须显式 `MODAL_GPU=…`。`modal deploy` 才保存 snapshot。列表：`modal run hydrate_modal.py --action profiles`

示例工作流在 `examples/`。LTX-2.5 官方 JSON 不能直接 `POST /prompt`，见文档「工作流与锁文件」。

本机控制面（会打开浏览器，顶栏选配方）：

```bash
python -m studio
```

Windows 也可以双击仓库根目录的 `open-studio.bat`。没有 Python 时下载 Releases 里的这一个 `Studio.exe`，双击即可。打开 `http://127.0.0.1:8787`，默认就是 Z-Image。下拉里还有 Z-Image-Turbo、FLUX.2 [dev]、Qwen-Image-2512、Krea-2 Turbo、Ideogram 4、Pixal3D、TripoSplat。密钥写在 `.studio.env`（单文件版在 `%LOCALAPPDATA%\ComfyStudio`），不会进 Git。见文档「Studio」。

后面加工作流不必再写一份 queue 脚本。先 `--inspect`，再 hydrate，再用 `python3 -m workflow_queue` 交给 ComfyUI 自己做 `graphToPrompt()`。官方那几百份模板先用 `python3 -m template_analyzer` 分类。解析器只绑定 JSON 里已经写明的 URL / CNR，不会为每个模板猜下载源。本机 App：`python -m studio`，打开后默认 Z-Image 配置；换配方只加 `catalog/<id>.json`。

## 开发

```bash
python -m unittest discover -s tests -v
```
