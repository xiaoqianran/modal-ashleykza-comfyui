# 故障排除

## GPU 跑完还不释放 / 一直在计费

默认冒烟是 **`modal deploy`**：空闲 5 秒缩到 0。不要 `modal app stop`（会丢掉快照）。`scaledown_window=5` **已经写在 Cls 上**，但这只在容器真正空闲时生效。常见原因：

1. leftover `modal serve` 还在本机跑（SIGINT 有时还留下容器）
2. 浏览器开着 ComfyUI，WebSocket 算活动
3. 脚本还在轮询 `/system_stats`
4. Pixal3D 等还在 `@modal.enter` 里编译，这是启动不是空闲

处理：

```bash
# 若误开了 serve，先停掉本机进程
pkill -INT -f "modal serve comfyui_modal.py" || true
modal container list
modal container stop <container-id>   # 有残留就立刻杀
```

Studio 生成结束后会默认停残留容器，不会卸掉已部署的 App。测试请用 **L40S**（`MODAL_GPU` 默认就是 L40S）。不要用 T4。不要把 `L40S,RTX-PRO-6000` 写进 fallback：Modal 会在 L40S 没货时改开贵卡。

## App has no function named 'ui'

旧版本曾用 `sys.argv` 判断是否注册 GPU 端点。远程 hydrate / deploy 的 argv 不含 `modal serve`，导致 `ui` 未定义。

当前 `comfyui_modal.py` **始终**注册 GPU UI。Hydrate 在独立 App 里。若仍看到此错误，确认部署的是最新 `main`。

## 缺模型 / Loader 找不到文件

1. `modal volume ls comfyui-ashleykza-models`
2. 对照工作流节点里的**精确文件名**
3. 确认 category：`diffusion_models` 不是随意别名
4. `modal run hydrate_modal.py --action resolve --workflow <file>` 查看 `unresolved`
5. 社区 JSON 缺 `cnr_id` / URL：`python3 -m manager_catalog --workflow <file>` 或 `hydrate --action probe`
6. 补 URL 后重新 `hydrate`

GPU 默认不会从 Hugging Face 现下。文件必须已经在 Volume 里。hydrate 完成后再发下一次 HTTP；已运行的容器在缩容后会 `Volume.reload()` 读到新的 `launch.json`。`modal serve` 没有持久快照，只有改 GPU 端 `.py` 才用。`modal deploy` 的 memory snapshot 只冻结 ComfyUI 进程；`snap=False` 仍会读最新 Volume。

## 模型或成片套了两层目录

例如 `vae/vae/*.safetensors` 或 `output/output/*.mp4`。这是旧下载把 category 又拼进文件名导致的。

当前 `storage.py` 在 hydrate 和 GPU 启动时会摊平。也可以只跑 CPU：

```bash
modal run hydrate_modal.py --action repair
modal run hydrate_modal.py --action outputs
```

正确位置永远是：

- 模型：`/mnt/comfy-storage/<category>/<filename>`
- 成片：`/workspace/output/<filename>`（Volume 上是 `/output/<filename>`）


## modal run hydrate 在构建巨大 GPU Image

用错了入口。请使用 `hydrate_modal.py`，不要 `modal run comfyui_modal.py` 做下载。

## 冷启动仍然很慢

- `modal serve` **不保存** snapshot，请用 `modal deploy`
- 换了 GPU 类型会重新捕获 snapshot
- 快照不能加速「权重从磁盘装进 VRAM」；第一张图仍可能要额外几十秒
- 确认没有误开 `COMFY_LATEST=1` / `COMFY_BASE_NODES=1` / `COMFY_INSTALL_NODES=1`（会重建节点 Image）

## 换工作流每次都在重建 Image

锁内 CNR 不能写进 Image 的 `run_commands` / `add_local_file`。当前实现里 hydrate 只更新 Volume `.state/launch.json`，`modal deploy comfyui_modal.py` 应复用同一 Image。若日志里仍在 `Building image` 且层哈希在变，检查是否带了 `COMFY_INSTALL_NODES=1` 或 `COMFY_BASE_NODES=1`。

## Secret 找不到

```bash
modal secret create comfyui-creds --from-dotenv .env --force
```

名称必须与 `MODAL_SECRET_NAME` 一致，默认 `comfyui-creds`。Civitai 变量名是 `CIVITAI_TOKEN`，不是 `CIVITAI_API_TOKEN`。

## GitHub clone 失败 / 限额

在 Secret 里提供 `GITHUB_TOKEN`。锁内 CNR 默认会装到 workspace Volume。130 个上游克隆只要 `COMFY_BASE_NODES=1`。

## 工作流仍有 unresolved

锁文件不会猜测下载地址。把 `name` + `directory` + http(s) URL 写进工作流的 `models` 数组，或把 HuggingFace / Civitai 直链写进 Note（文件名必须对得上 widget）。也可以先走 ComfyUI-Manager 同一份表：

```bash
python3 -m manager_catalog --workflow examples/你的.json
modal run hydrate_modal.py --action probe --workflow examples/你的.json
```

一对一命中才写入；两个 URL / 未知 `models/` 目录仍留 `unresolved`。Manager 的模型表覆盖不全，探测**不能保证**下到所有权重。不要为此再写一份 `queue_*.py`。

若 `unresolved` 条目已经带了 `url`、`reason` 为 `missing_category`，只差补 ComfyUI 目录名，再挪进 `models`。手修 `.lock.json` 后也可以 hydrate。已手修的 fully resolved 锁不会被 `probe` 覆盖。

## Pages 文档 404

仓库 Settings → Pages → Source 选 **GitHub Actions**。推送到 `main` 后查看 Actions 里的 **Deploy documentation** 工作流。
