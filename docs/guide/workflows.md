# 工作流与锁文件

GPU 启动前，工作流引用的权重必须已经在 Storage 里。锁文件描述「这份工作流需要哪些文件、从哪下载」。

## 生成锁文件

```bash
modal run hydrate_modal.py --action resolve --workflow examples/z-image-base.json
```

默认写出 `examples/z-image-base.lock.json`。`--workflow` 不带 `--action resolve` 时会再下载模型。插件写入 `custom_nodes`，默认不安装。

解析器遍历：

- 普通 ComfyUI `nodes` 与嵌套子图
- API prompt 的 `class_type` 节点
- 根级或节点级 `models` 数组
- widget / API input 中的常见模型后缀

只找到文件名而没有 URL 时，记入 `unresolved`，**不会猜测下载源**。`hydrate` 在 `require_resolved=True` 时遇到未解析项会失败。

## 锁文件 schema 1

仓库里的 `examples/z-image-base.lock.json` 结构如下：

```json
{
  "schema": 1,
  "workflow": { "name": "z-image-base.json", "sha256": "..." },
  "models": [
    {
      "category": "diffusion_models",
      "filename": "z_image_bf16.safetensors",
      "url": "https://huggingface.co/…/z_image_bf16.safetensors",
      "sha256": null,
      "source": "node:UNETLoader"
    }
  ],
  "custom_nodes": [],
  "unresolved": []
}
```

校验器会拒绝绝对路径、`..`、重复目标、非 HTTP(S) URL、非法 CNR id 以及非 SHA256 哈希。锁文件可以提交 Git；其中不含 token，认证只从 Modal Secret 注入。

手工补全未解析项时，把对象加入 `models` 并删除 `unresolved` 中的对应条目：

```json
{
  "category": "checkpoints",
  "filename": "vendor/model.safetensors",
  "url": "https://example.com/model.safetensors",
  "sha256": null,
  "source": "manual"
}
```

部署时把锁文件打进 GPU Image（启动前做存在性检查）：

```bash
COMFY_WORKFLOW=examples/z-image-base.json modal deploy comfyui_modal.py
```

## 仓库示例：Z-Image

| Storage 路径 | 作用 |
|---|---|
| `diffusion_models/z_image_bf16.safetensors` | UNet / DiT |
| `text_encoders/qwen_3_4b.safetensors` | 文本编码器 |
| `vae/ae.safetensors` | VAE |

对应文件：`examples/z-image-base.json` 与 `examples/z-image-base.lock.json`。

## 自定义工作流

1. 在本地 ComfyUI 导出 API / workflow JSON（或带嵌入工作流的 PNG）。
2. `resolve` 查看 `unresolved`；缺 URL 就补进 JSON 或锁文件。
3. `hydrate` 写入 Storage。
4. `modal volume ls comfyui-ashleykza-models` 确认 category 与文件名。
5. `modal deploy` 后在 UI 里加载**同一份** JSON。

文件名必须与 Loader 节点里填的字符串完全一致（含扩展名）。

!!! note "UI 里临时拖入的新工作流"
    已经在跑的 GPU 容器事先不知道新 JSON。正确做法是先拿到文件 → hydrate → 再部署或开新容器。GPU 端不会回退到在线安装。

## 无法自动解决的情况

- 工作流只有本地文件名，没有 URL
- custom node 缺少 CNR 元数据且不在 Recipe
- 下载需要网页交互或自定义授权
- 模型名由节点运行时动态计算
- 工作流依赖的 ComfyUI 版本与当前 Image 不兼容
