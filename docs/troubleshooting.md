# 故障排除

## App has no function named 'ui'

旧版本曾用 `sys.argv` 判断是否注册 GPU 端点。远程 hydrate / deploy 的 argv 不含 `modal serve`，导致 `ui` 未定义。

当前 `comfyui_modal.py` **始终**注册 GPU UI。Hydrate 在独立 App 里。若仍看到此错误，确认部署的是最新 `main`。

## 缺模型 / Loader 找不到文件

1. `modal volume ls comfyui-ashleykza-models`
2. 对照工作流节点里的**精确文件名**
3. 确认 category：`diffusion_models` 不是随意别名
4. `modal run hydrate_modal.py --action resolve --workflow <file>` 查看 `unresolved`
5. 补 URL 后重新 `hydrate`

GPU 默认不会从 Hugging Face 现下。文件必须已经在 Volume 里。hydrate 完成后再开新的 GPU 容器；已运行的容器看不到尚未 `commit` / 尚未重建的 Volume 快照。

## modal run hydrate 在构建巨大 GPU Image

用错了入口。请使用 `hydrate_modal.py`（App 名带 `-hydrate` 后缀），不要 `modal run comfyui_modal.py --action hydrate`。

## 冷启动仍然很慢

- `modal serve` **不保存** snapshot，请用 `modal deploy`
- 换了 GPU 类型会重新捕获 snapshot
- 快照不能加速「权重从磁盘装进 VRAM」；第一张图仍可能要额外几十秒
- 确认没有误开 `COMFY_LATEST=1`（会重建节点 Image）

## Secret 找不到

```bash
modal secret create comfyui-creds --from-dotenv .env --force
```

名称必须与 `MODAL_SECRET_NAME` 一致，默认 `comfyui-creds`。Civitai 变量名是 `CIVITAI_TOKEN`，不是 `CIVITAI_API_TOKEN`。

## GitHub clone 失败 / 限额

在 Secret 里提供 `GITHUB_TOKEN`，或使用 `COMFY_BASE_NODES=0` 跳过完整插件克隆。

## 工作流仍有 unresolved

锁文件不会猜测下载地址。把 URL 写进工作流的 `models` 数组，或手工编辑 `.lock.json` 后再 hydrate。

## Pages 文档 404

仓库 Settings → Pages → Source 选 **GitHub Actions**。推送到 `main` 后查看 Actions 里的 **Deploy documentation** 工作流。
