# Studio（Z-Image）

引擎（hydrate / Volume / GPU ComfyUI）保持不动。Studio 是本机控制面：读 `catalog/` 里的配方契约，把提示词和参数打成 `POST /prompt`。

密钥只写在本机 `.studio.env`（已 gitignore）。Modal token 用来调你自己的 workspace；HF / GitHub / Civitai 再写入你的 `comfyui-creds` Secret。页面默认只绑 `127.0.0.1`。

## 启动

```bash
python -m studio
```

打开 [http://127.0.0.1:8787](http://127.0.0.1:8787)。

1. 填 Modal token（或留空，沿用 `modal setup` 的 CLI 登录）和 `HF_TOKEN`，保存。
2. **准备权重**：`modal run hydrate_modal.py --workflow examples/z-image-base.json`
3. **启动 GPU**：本机拉起 `modal serve`（按 catalog 默认 GPU，可改）。
4. 也可以把已经在跑的 `*.modal.run` 贴进「Comfy 地址」。
5. 提示词一行一条，调步数 / CFG / 尺寸 / 种子，生成。同一张 GPU 上是 Comfy 队列，不是多卡并行。

## 契约

`catalog/z-image.json` 绑定：

- 工作流 / 锁文件
- 推荐 GPU
- 用户能改的参数
- API prompt graph（`$prompt` `$seed` 等占位符）

以后加 LTX / Pixal3D，是再加一份 catalog，而不是改 `comfy_engine.py`。

CLI 批量出图仍可用：

```bash
python3 scripts/run_z_image_prompts.py --base-url https://<your>.modal.run
```

它现在也从同一份 catalog 绑 graph。
