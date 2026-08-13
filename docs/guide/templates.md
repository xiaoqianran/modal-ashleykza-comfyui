# Comfy-Org 官方模板

[Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates/tree/main/templates) 里有约 580 份 UI JSON。不要整仓推进本仓库（大量 webp）。只要 JSON：

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/Comfy-Org/workflow_templates.git
cd workflow_templates
git sparse-checkout set templates
# 可选：只留 json
find templates -type f ! -name '*.json' -delete
```

然后静态分类（不占 GPU、不下载权重）：

```bash
python3 -m template_analyzer --dir workflow_templates/templates \
  --out artifacts/templates-report.json
```

## 分类结果（一次全量扫描）

| 桶 | 大约数量 | 含义 |
|---|---|---|
| `api_cloud` | 229 | 文件名 `api_*`，走付费/云端 API 节点，不在本机 GPU 上跑 |
| `hydrate_ready` | ~220 | 锁能解析、权重有 URL、只要 comfy-core |
| `core_no_weights` | ~60 | 核心节点、没有模型（调色 / 开关等） |
| `needs_cnr` | ~40 | 要装 Comfy Registry 自定义节点 |
| `parse_fail` | ~20 | 锁解析失败（CNR 版本冲突、重复 URL 等） |
| `unresolved_models` | ~10 | 扫到了文件名但没有下载地址 |

**可行：** 大约一半本地模板可以走现有路径：hydrate → 同一套 GPU Image → `/workspace/output`。不必每个 JSON 写脚本。网页 Queue，或 `python3 -m workflow_queue`。

**不可行 / 先别碰：** 全部 `api_*`；需要一堆社区节点的 `template_*`；解析失败的先修 analyzer/resolver。

## 试水建议（便宜、本机）

先不要上 30GB+ 的 Flux/WAN。分类器会列出 `vram <= 16GB` 且 `hydrate_ready` 的名单，例如 BiRefNet、MoGe、SDPose、SDXL Simple。`basic_image_color_adjustment` 属于 `core_no_weights`，几乎不占显存，适合验证「JSON → inspect → 进 ComfyUI」这条链。

官方 `index.json` 里的 `vram` 有的是字节、有的缺省成 0，**0 不当成真的零成本**。

## 已知缺口

- `model_patches/` 已加入 Storage 目录表，否则官方 ControlNet patch 模板会解析失败
- 同一工作流里同一个 CNR id 写了两个 git hash 时，现有锁校验会拒绝（正确，不要猜）
- subgraph 的 UUID 节点类型，`--inspect` 只能看到外壳；真正展平仍靠运行中的 `graphToPrompt()`
