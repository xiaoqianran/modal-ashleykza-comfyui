# 架构

产品分三层。Studio 和排队只认 **catalog**；`recipes.PROFILES` 只给旧的 hydrate 模型包用。

```text
运行时
  comfyui_modal.py      GPU App：Cls UI + web_server（端口 3001）
  hydrate_modal.py      CPU App：hydrate / resolve / profiles / outputs / repair
  modal_config.py       常量、路径、环境变量
  storage.py            Volume 路径与 extra_model_paths.yaml
  comfy_engine.py       下载、校验、启动 ComfyUI
  sparse_3d_runtime.py  Pixal3D / TRELLIS CUDA wheels（装到 workspace Volume）
  workflow_resolver.py  工作流 → 锁文件（只绑定 JSON 里已有的 URL / CNR）
  recipes.py            MODEL_DIRS + 旧 profile / model pack / node pack

catalog
  catalog/*.json        Studio 配方契约（表单 / GPU / 绑定；不是 Python 适配器）
  catalog/gates.py      例外闸门：mode=graph / 非 L40S 默认卡 / queue_*.py / LTX 不进 catalog
  workflow_queue.py     通用排队：graphToPrompt → /prompt → 取件
  recipe_scaffold.py    新配方脚手架：workflow + lock + catalog + overlay 草稿
  benchmarks.py         实测 overlay → docs/guide/models.md + Studio 配方表

Studio
  studio/               本机 UI；读 catalog，调 hydrate / serve / workflow_queue
  packaging/            Windows Studio.exe
  gallery_hub/          HF 图库数据集（推送 / 拉取 / 编进 Pages）

其它
  base_nodes.py         基础自定义节点安装（默认关，会改 Image）
  scripts/queue_ltx25.py  Ashley 0.32.0 缺官方节点时的补丁；HTTP 走 workflow_queue
  examples/             示例 workflow / lock
  docs/                 本站点 Markdown
  mkdocs.yml            MkDocs Material 配置
```

三层之间：**hydrate / GPU 不 import catalog**。`--catalog <id>` 只在本机入口把 id 换成 `examples/*.json` 路径，之后仍走原来的 workflow 锁。`storage.py` / `workflow_resolver.py` 只用 `recipes.MODEL_DIRS`，不用 `PROFILES`。

## 配方从哪来

| 表面 | 给谁用 | 不要当成 |
|---|---|---|
| `catalog/<id>.json` | Studio 顶栏、`hydrate --catalog`、`python3 -m workflow_queue` | 每条配方一份 Python 适配器 |
| `recipes.PROFILES` | 旧 hydrate 包：`nordy-*` / `wan22` / `ltx23` / `qwen-image` 等 | Studio 配方表 |
| `recipes.MODEL_DIRS` | 锁解析与 Storage 目录 | 产品目录 |

完整 Studio 表见 [模型列表](../guide/models.md)。旧 profile 表见 [旧 hydrate 配方](../guide/recipes.md)。LTX-2.5 仍走手修锁 + `scripts/queue_ltx25.py`，不进 catalog（`catalog.gates.OUT_OF_CATALOG_WORKFLOWS`）。

新配方必须 `mode=workflow`。`mode=graph` 只允许 `catalog.gates.GRAPH_MODE_IDS`（Z-Image / Z-Image-Turbo）。测试默认非 L40S 只允许 `NON_L40S_DEFAULT_GPU_IDS`。`scripts/queue_*.py` 只允许 `ALLOWED_QUEUE_SCRIPTS`。扩这些集合要在 PR 里写原因，不要再写适配器。

## GPU 类

`UI`（`comfyui_modal.py`）：

- `enable_memory_snapshot=True`（可用 `COMFY_MEMORY_SNAPSHOT=0` 关闭）
- `experimental_options={"enable_gpu_snapshot": True}`（可用 `COMFY_GPU_SNAPSHOT=0` 关闭）
- `@modal.enter(snap=True) snapshot_runtime()`：按当时的 Volume launch.json 装 CNR 并启动 ComfyUI（写入 deploy 快照）
- `@modal.enter(snap=False) apply_launch()`：`Volume.reload()` 后按**当前** launch.json 校验/装 CNR；指纹变化或新装节点时重启 ComfyUI
- `@modal.web_server ui()`：空方法，端口 **3001** 已在 listen
- `@modal.exit() stop()`：`commit()` workspace Volume，再终止 ComfyUI
- `@modal.concurrent` + `max_containers=1`

不要根据 `sys.argv` 决定是否注册 `ui`。远程容器里的 argv **不是** `modal serve`，否则会得到 `App has no function 'ui'`。

## Image 分层

默认 Image 对所有工作流相同，才能吃到 Modal 层缓存：

1. 构建时解析最新 Ashley `cu128-py312-v*`（不钉 0.32 / 0.33；`COMFY_IMAGE` 可覆盖）
2. 静态 musl `uv` + `uvx`（不靠 pip 引导）
3. `uv pip --python` 装 `typing_extensions` / `pydantic` 与固定 `comfy-cli==1.16.0`
4. `COMFY_BASE_NODES=1`：约 130 个 GitHub 节点（默认关，会改 Image；依赖用 `uv pip`）
5. `COMFY_INSTALL_NODES=1`：profile 额外 node packs（默认关，会改 Image）

工作流锁里的 CNR **不在 Image 里**。hydrate 写入 `.state/launch.json`，GPU 启动时装到 `/workspace/custom_nodes`。

`COMFY_LATEST=1` 才会强制重建节点层。

## Volume 提交

CPU Function 在成功路径调用 `models_vol.commit()` 与 `workspace_vol.commit()`。GPU 在首次把 CNR 写入 `/workspace/custom_nodes`、或把 CUDA wheels 写入 `/workspace/.python/sparse-3d` 后也会 `workspace_vol.commit()`，否则缩容后下次还会再装一遍。SaveVideo 写入 `/workspace/output` 后由后台 watch 再 `commit()`；`@modal.exit()` 再提交一次。成片不需要 GPU 容器继续活着，用 hydrate CPU `--action outputs` 或 `modal volume get` 读取。

CUDA wheels 不进 Image、也不进 models Volume。冷启动时 `sparse_3d_runtime` 用 `uv pip install --target /workspace/.python/sparse-3d`，wheel 文件缓存在 `/workspace/.python/wheels`，再往容器 venv 的 site-packages 写一个 `comfy_sparse_3d.pth`。`.pth` 随 Image venv 一起消失，Volume 上的 site 还在；下次只要重新写 `.pth` 就能 import。Blackwell 的 boot `.pth` 仍写在 venv 里（几行 Python）。OpenGL 的 `apt-get` 仍是每次冷启动。CNR / GitHub 节点的 `requirements.txt` 同样装到 `/workspace/.python/node-reqs`，venv 里只留 `comfy_node_reqs.pth`；`requirements.txt` 的 sha256 对上就跳过 `uv pip`。

## 隔离冷启动：哪些能复用

codegraph（AST 调用链）把 GPU 启动收成一条线：

```text
UI.snapshot_runtime (snap=True)
UI.apply_launch     (snap=False)  → stop_comfyui → Volume.reload
        └─ apply_volume_launch
              ├─ prepare_runtime
              ├─ verify_workflow_models
              ├─ ensure_pixal3d_prebuilt_wheels → _prepare_sparse_3d_site → .pth
              ├─ ensure_node_reqs_site          → comfy_node_reqs.pth
              ├─ install_registry_nodes
              │     ├─ skip clone when Volume marker matches
              │     └─ _install_node_requirements  → uv pip --target node-reqs
              └─ ensure_pixal3d_runtime
```

| 层 | 第一次冷启动 | 缩容后再来 | 不能复用的原因 |
|---|---|---|---|
| 模型文件 | hydrate 写入 models Volume | `Volume.reload()` 后直接用 | — |
| CNR / git clone | 装到 `/workspace/custom_nodes` 并 `commit` | marker + 目录在就 `[SKIP]` | — |
| CUDA wheels | `--target /workspace/.python/sparse-3d` | 只重写 `.pth` | Image venv 是一次性的 |
| 节点 `requirements.txt` | `--target /workspace/.python/node-reqs` | hash 命中则跳过 `uv pip` | 以前装进 venv，缩容就没了 |
| Memory / GPU snapshot | 只在 **`modal deploy` 之后** | 恢复进程，再 `snap=False` 对一下指纹 | `modal serve` 不写快照 |
| Isolation worker 进程 | 容器内拉起 | 必须再拉一次 | 进程跟容器一起死 |
| OpenGL `apt-get`、Blackwell boot `.pth` | 每次写进当前容器 | 每次都做（便宜） | 不在 Volume 上 |

冒烟默认 **`modal deploy`**：0 tasks 不计 GPU，快照跨冷启动复用。`modal serve` 热加载的是本地 `.py`，**不是** GPU 内存；serve 进程还在就会挡住缩容。只有改 GPU 端 Python 才用 serve。SAM 3D 的 pixi / comfy-env 隔离在配方分支上，主线这条链不经过它。

## Volume 路径

所有路径由 `storage.py` 规范化：去掉重复的 `models/`、category、`output/` 前缀；hydrate 与 GPU 启动时摊平已套层的目录。成片只在 workspace Volume 的 `/output`。
