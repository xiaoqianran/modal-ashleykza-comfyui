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

## 分类结果（一次全量扫描，583 份 JSON）

| 桶 | 数量 | 含义 |
|---|---|---|
| `api_cloud` | 229 | 文件名 `api_*`，走付费/云端 API 节点，不在本机 GPU 上跑 |
| `hydrate_ready` | 230 | 锁能解析、权重有 URL、只要 comfy-core |
| `core_no_weights` | 59 | 核心节点、没有模型（调色 / 开关等） |
| `needs_cnr` | 56 | 要装 Comfy Registry 自定义节点（含 CNR 版本冲突后仍选出一版的） |
| `unresolved_models` | 9 | 扫到了文件名，JSON 里没有能用的下载地址或目录 |
| `parse_fail` | 0 | 整份 JSON 被拒绝（路径穿越等才应落到这里） |

**可行：** 大约一半本地模板可以走现有路径：hydrate → 同一套 GPU Image → `/workspace/output`。不必每个 JSON 写脚本。网页 Queue，或 `python3 -m workflow_queue`。

**不可行 / 先别碰：** 全部 `api_*`；JSON 里只有文件名、没有 URL 的社区模板；CNR 装完仍缺节点的再另说。缺地址的去补 `models[]` 或手修锁，**不要**为此写 `queue_*.py`。

## 试水建议（便宜、本机）

先不要上 30GB+ 的 Flux/WAN。分类器会列出 `vram <= 16GB` 且 `hydrate_ready` 的名单，例如 BiRefNet、MoGe、SDPose、SDXL Simple。`basic_image_color_adjustment` 属于 `core_no_weights`，几乎不占显存，适合验证「JSON → inspect → 进 ComfyUI」这条链。

官方 `index.json` 里的 `vram` 有的是字节、有的缺省成 0，**0 不当成真的零成本**。

## 解析边界（不要为每个模板写适配）

自动下载**只信 JSON 里已经写明的东西**，不猜 HuggingFace 仓库、不猜 GitHub 插件地址。

**会自动进锁：**

1. 根级或节点 `properties.models[]`：同时有 `name`、`directory`、`http(s)` URL
2. widget 里的权重文件名，其 **basename** 能对上上面的 URL，或 Note / MarkdownNote 里的 HuggingFace / Civitai **带文件名**的链接（`/blob/` 会改成 `/resolve/`，`?download=true` 会去掉）
3. `properties.cnr_id` + `ver` → GPU 启动时 `comfy node registry-install` 装到 Volume

同一 CNR 写了两个版本时**不整份失败**：优先 semver，其次出现次数更多的 git hash，冲突写进 `warnings`。同一文件两个 URL 只差查询串时视为同一地址。

Storage 目录表只扩官方 ComfyUI / 官方模板真实在用的文件夹（现有基础上加了 `audio_encoders`、`detection`、`frame_interpolation`、`optical_flow`、`model_patches`）。未知目录记 warning，不中止整份解析。

**拒绝自动、也不为此写脚本：**

| 情况 | 做法 |
|---|---|
| `api_*` 云端节点 | 不要在本机 GPU 跑 |
| 只有文件名，笔记里也没有可下载 URL | `unresolved`，hydrate 失败；把 URL 写进 JSON 或锁 |
| 笔记 URL 对上了文件名，但看不出 `models/<目录>` | `unresolved` 会带上 URL，只差人手补目录 |
| 同一目标两个不同文件 / 两个 SHA256 | 丢掉该条，不猜该下哪份 |
| 节点没有 `cnr_id` | 不编造 GitHub 仓库 |
| 路径穿越、`file://` | 拒绝；`file://` 跳过该条，不中止其余解析 |

运行时仍然只有一条路。缺的是锁里的 URL / CNR，不是又一个 `queue_*.py`。

## 已知缺口

- 约 9 份本地模板仍是「有文件名、无下载地址」（AnimateDiff / OpenPose / FILM 等老模板），只能手补
- subgraph 的 UUID 节点类型，`--inspect` 只能看到外壳；真正展平仍靠运行中的 `graphToPrompt()`
