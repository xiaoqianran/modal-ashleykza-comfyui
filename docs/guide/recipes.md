# 旧 hydrate 配方

> **Studio 不用这张表。** 顶栏配方、GPU、实测在 [模型列表](models.md)，契约在 `catalog/*.json`。
>
> `recipes.PROFILES` 只给 `hydrate --profile` 下载一组旧模型包（nordy / wan / ltx23 等）。不要把新的 Studio 配方写进这里，也不要把 LTX-2.5 塞进 catalog。

```bash
modal run hydrate_modal.py --catalog z-image
modal run hydrate_modal.py --action profiles
modal run hydrate_modal.py --profile qwen-image
modal deploy comfyui_modal.py
```

`--action profiles` 会先打印上面这句说明，再列出旧 pack，最后列出 Studio catalog id。

未指定 `--catalog` / `--workflow` 时默认 `COMFY_PROFILE=base`。配方里的 **node packs 默认不安装**。

## 当前旧 pack

| 名称 | 模型包 | 额外节点 | 说明 |
|---|---|---|---|
| `base` | — | — | 仅 Ashley runtime（130 个基础节点需 `COMFY_BASE_NODES=1`） |
| `ltx23` | `ltx23` | — | LTX 2.3 |
| `nordy-kontext-views` | `nordy-kontext-views` | `flux-kontext-extra` | FLUX Kontext 多视图 |
| `nordy-clothes` | `nordy-clothes` | `nordy-clothes-extra` | 服装 / inpaint |
| `qwen-image` | `qwen-image` | `qwen-image-extra` | Qwen Image |
| `flux-krea` | `flux-krea` | — | FLUX.1 Krea |
| `flux-kontext` | `flux-kontext` | `flux-kontext-extra` | FLUX Kontext + omini-kontext |
| `wan22` | `wan22` | — | Wan 2.2 模型（Wan/KJ/VHS/GGUF 节点需 `COMFY_BASE_NODES=1`） |
| `wan22-notebook-full` | `wan22` | `wan-notebook-extra` | Wan 2.2 + notebook 额外节点 |
| `nunchaku` | — | `nunchaku` | Nunchaku 节点 |

Z-Image 走 catalog，不要用 profile：

```bash
modal run hydrate_modal.py --catalog z-image
```

名称、模型 URL 与节点仓库以仓库当前 `recipes.py` 为准。`MODEL_DIRS` 仍给锁解析和 Storage 用，没有废掉。
