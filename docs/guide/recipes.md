# 配方

`recipes.py` 里的 **profile** 把一组模型包和额外节点绑在一起，给 hydrate 与 GPU Image 使用。

```bash
modal run hydrate_modal.py --action profiles
modal run hydrate_modal.py --profile qwen-image
modal deploy comfyui_modal.py
```

未指定时默认 `COMFY_PROFILE=base`。配方里的 **node packs 默认不安装**。

## 当前配方

| 名称 | 模型包 | 额外节点 | 说明 |
|---|---|---|---|
| `base` | — | — | Ashley runtime + 基础节点 |
| `ltx23` | `ltx23` | — | LTX 2.3 |
| `nordy-kontext-views` | `nordy-kontext-views` | `flux-kontext-extra` | FLUX Kontext 多视图 |
| `nordy-clothes` | `nordy-clothes` | `nordy-clothes-extra` | 服装 / inpaint |
| `qwen-image` | `qwen-image` | `qwen-image-extra` | Qwen Image |
| `flux-krea` | `flux-krea` | — | FLUX.1 Krea |
| `flux-kontext` | `flux-kontext` | `flux-kontext-extra` | FLUX Kontext + omini-kontext |
| `wan22` | `wan22` | — | Wan 2.2（Wan/KJ/VHS/GGUF 已在基础节点中） |
| `wan22-notebook-full` | `wan22` | `wan-notebook-extra` | Wan 2.2 + notebook 额外节点 |
| `nunchaku` | — | `nunchaku` | Nunchaku 节点 |

Z-Image 示例不走 profile，直接：

```bash
modal run hydrate_modal.py --workflow examples/z-image-base.json
```

名称、模型 URL 与节点仓库以仓库当前 `recipes.py` 为准。
