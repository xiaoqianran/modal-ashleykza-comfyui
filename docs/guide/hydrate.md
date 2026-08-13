# Hydrate Storage

CPU 把权重写入 Volume `comfyui-ashleykza-models`。不构建 GPU Image，**也不安装插件**。

## 两种方式

=== "工作流"

    ```bash
    modal run hydrate_modal.py --workflow examples/z-image-base.json
    ```

    解析 JSON（或带工作流的 PNG）：模型 URL、CNR 插件 id。模型并行下载；插件只写入 `.lock.json`。

=== "Profile"

    ```bash
    modal run hydrate_modal.py --profile qwen-image
    ```

    下载 `recipes.py` 里该配方的 **model packs**。node packs 默认跳过。

只解析、不下载：

```bash
modal run hydrate_modal.py --action resolve --workflow examples/z-image-base.json
```

| 参数 | 说明 |
|---|---|
| `--workflow` | 工作流 JSON / PNG → workflow 模式 |
| `--profile` | 配方名 → profile 模式（默认 `base`） |
| `--lock-out` | 锁文件路径；默认把工作流后缀改成 `.lock.json` |
| `--action` | `hydrate`（默认）、`resolve`、`profiles`、`info` |

给了 `--workflow` 就是 workflow 模式，不再用 profile 拉模型包。

## 并行

默认 4 路（`COMFY_HYDRATE_WORKERS`，1–16）。8 CPU / 16 GiB，超时 6 小时。

已存在且匹配则 `[SKIP]`；旧 workspace 布局会 `[PROMOTE]`。成功后 `commit()` 两个 Volume。
