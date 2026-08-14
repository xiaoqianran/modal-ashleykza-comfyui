# Hydrate Storage

CPU 把权重写入 Volume `comfyui-ashleykza-models`。不构建 GPU Image。插件写入 lock 和 Volume `.state/launch.json`，由 GPU **启动时**装到 `/workspace/custom_nodes`（已存在则跳过）。换工作流不会重建 GPU Image。

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

    解析 JSON（或带工作流的 PNG）：`models[]` 里的 URL、Note 里能对上文件名的 HuggingFace / Civitai 直链、CNR 插件 id。模型并行下载；插件写入 `.lock.json` 和 Volume state。`modal serve` 时按 CNR 往 Volume 安装，不打进 Image。猜不出来的下载源不会编造，见 [工作流与锁文件](workflows.md)。

=== "旧 Profile"

    ```bash
    modal run hydrate_modal.py --profile qwen-image
    ```

    下载 `recipes.py` 里该 **legacy pack** 的 model packs。Studio 不用这张表。node packs 默认跳过。

只解析、不下载：

```bash
modal run hydrate_modal.py --action resolve --workflow examples/z-image-base.json
```

| 参数 | 说明 |
|---|---|
| `--catalog` | Studio 配方 id → 换成该 JSON 的 workflow / lock |
| `--workflow` | 工作流 JSON / PNG → workflow 模式 |
| `--profile` | 旧 hydrate pack 名 → profile 模式（默认 `base`；Studio 不用） |
| `--lock-out` | 锁文件路径；默认把工作流后缀改成 `.lock.json` |
| `--skip-lock-nodes` | 写入 launch.json，让 GPU 启动时跳过 CNR |
| `--install-nodes` | hydrate 上无效；配方额外包请在 GPU serve/deploy 设 `COMFY_INSTALL_NODES=1` |
| `--action` | `hydrate`（默认）、`sync` / `workflow-sync`、`resolve`、`profiles`、`info`、`outputs`、`repair` |

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
