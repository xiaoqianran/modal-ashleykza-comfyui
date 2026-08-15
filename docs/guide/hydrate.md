# Hydrate Storage

CPU 把权重写入 Volume `comfyui-ashleykza-models`。不构建 GPU Image。插件写入 lock 和 Volume `.state/launch.json`，由 GPU **启动时**装到 `/workspace/custom_nodes`（已存在则跳过）。换工作流不会重建 GPU Image。

社区 JSON 常常没有 `cnr_id`、也没有 `models[]` URL。网页里加载工作流后点 **Install Missing Custom Nodes** / Model Manager **In Workflow** 的，是 [ComfyUI-Manager](https://github.com/Comfy-Org/ComfyUI-Manager)。本仓库用同一份目录（`extension-node-map.json`、`model-list.json`），走 CPU，不必先开 GPU：

```text
A  CPU 起一份 ComfyUI --cpu（Volume `.cpu-comfy`，不计 GPU）
B  Manager 目录补锁 → 已绑定的权重在 CPU 下载
C  modal deploy 上 GPU（CUDA 节点仍在 GPU 启动时装）
```

默认 `hydrate` 仍是解析器只绑定 JSON 里已有的 URL / CNR，**不猜** HuggingFace 仓库。要走 Manager + CPU 探测用 `--action probe`。

## 三种方式

=== "Catalog"

    ```bash
    modal run hydrate_modal.py --catalog z-image
    ```

    与 Studio 顶栏同一份 `catalog/<id>.json`，换成里面的 `workflow` / `lock` 路径再走下面的工作流模式。完整 id 见 [模型列表](models.md)。

=== "工作流"

    ```bash
    modal run hydrate_modal.py --workflow examples/z-image-base.json
    ```

    解析 JSON（或带工作流的 PNG）：`models[]` 里的 URL、Note 里能对上文件名的 HuggingFace / Civitai 直链、CNR 插件 id。模型并行下载；插件写入 `.lock.json` 和 Volume state。GPU 启动时按 CNR 往 Volume 安装，不打进 Image。猜不出来的下载源不会编造，见 [工作流与锁文件](workflows.md)。

=== "旧 Profile"

    ```bash
    modal run hydrate_modal.py --profile qwen-image
    ```

    下载 `recipes.py` 里该 **legacy pack** 的 model packs。Studio 不用这张表。node packs 默认跳过。

只解析、不下载：

```bash
modal run hydrate_modal.py --action resolve --workflow examples/z-image-base.json
```

社区 JSON 缺 URL / `cnr_id` 时，用 Manager 目录 + CPU ComfyUI 探测（第一次会在 Volume 上 clone ComfyUI 并装 CPU torch，之后复用）：

```bash
modal run hydrate_modal.py --action probe --workflow examples/你的.json
# 或
modal run hydrate_modal.py --action probe --catalog z-image
python3 -m manager_catalog --workflow examples/你的.json
MODAL_GPU=L40S modal deploy comfyui_modal.py
```

`--action probe` 仍不猜地址：Manager 表里一对一命中才写入锁；文件名对应两个 URL、或 `save_path` 不是已知 `models/` 目录，留在 `unresolved`。已手修且 fully resolved 的 `.lock.json` **不会**被覆盖。锁还没齐时只下载已经绑定的权重，**不**写 Volume `launch.json`（避免 GPU 当成齐套工作流）。CUDA 专用节点在 CPU 上 import 失败是预期，会出现在 `probe.missing_nodes_in_lock`；真正安装仍在步骤 C。

| 参数 | 说明 |
|---|---|
| `--catalog` | Studio 配方 id → 换成该 JSON 的 workflow / lock |
| `--workflow` | 工作流 JSON / PNG → workflow 模式 |
| `--profile` | 旧 hydrate pack 名 → profile 模式（默认 `base`；Studio 不用） |
| `--lock-out` | 锁文件路径；默认把工作流后缀改成 `.lock.json` |
| `--skip-lock-nodes` | 写入 launch.json，让 GPU 启动时跳过 CNR |
| `--install-nodes` | hydrate 上无效；配方额外包请在 GPU serve/deploy 设 `COMFY_INSTALL_NODES=1` |
| `--action` | `hydrate`（默认）、`sync` / `workflow-sync`、`resolve`、`probe`、`profiles`、`info`、`outputs`、`repair` |

给了 `--workflow` 就是 workflow 模式，不再用 profile 拉模型包。

## 并行

默认 4 路（`COMFY_HYDRATE_WORKERS`，1–16）。8 CPU / 16 GiB，超时 6 小时。

已存在且匹配则 `[SKIP]`；旧 workspace 布局会 `[PROMOTE]`。成功后 `commit()` 两个 Volume。

GPU 空闲 5s 后应缩到 0。成片在 workspace Volume 的 `/output`，用 CPU 读取：

```bash
modal run hydrate_modal.py --action outputs
modal run hydrate_modal.py --action repair
modal volume get comfyui-ashleykza-workspace /output ./output
```
