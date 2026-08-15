# GPU 部署

先 hydrate，再 **`modal deploy`**。不要用 `modal serve` 做冒烟——本机进程会挡住 5 秒缩容，GPU 一直计费。

```bash
modal run hydrate_modal.py --catalog z-image
MODAL_GPU=L40S modal deploy comfyui_modal.py
python3 -m workflow_queue --base-url https://<workspace>--comfyui-ashleykza-cu128-ui-ui.modal.run \
  --workflow examples/z-image-base.json --prompt "a celadon teapot"
```

`modal deploy` 本身**不占 GPU**。第一次打到 `*.modal.run` 才起容器。队列结束、没有人开着 ComfyUI 页，5 秒后缩到 0。App 留着，下次冷启动走 memory snapshot，又快又便宜。

| | `modal deploy`（默认） | `modal serve`（只有改 GPU 端 `.py`） |
|---|---|---|
| 空闲 5 秒缩容 | 会 | 本机进程挡住 |
| 快照 | 保存，后续冷启动复用 | 不保存 |
| 热加载本地 `.py` | 否，改完再 deploy | 是（一保存就换容器） |
| 第一次请求才起 GPU | 是 | serve 进程还在就会挡缩容 |

改 `comfyui_modal.py` / `sam3d_runtime.py` / `comfy_engine.py` 才用 serve。改 `workflow_queue.py` 不用——它在本机跑。

```bash
STUDIO_GPU_MODE=serve python -m studio   # 只在改 GPU 端 Python 时
```

测完**不必** `modal app stop`。停 App 会丢掉快照，下次更慢。要立刻释放残留容器：

```bash
modal container list
modal container stop <container-id>
```

Studio「部署 GPU」走同一条路径；生成结束后默认停残留容器，勾选「继续占着 GPU」才会留着。

换 GPU：默认 **L40S**。不要写一长串 fallback。不要用 T4。需要 RTX-PRO-6000 时显式 `MODAL_GPU=RTX-PRO-6000`。

锁内 CNR 默认在 GPU 启动时装到 Volume。关掉：hydrate 时 `--skip-lock-nodes`。配方额外节点：`COMFY_INSTALL_NODES=1`（改 Image）。130 个上游基础节点：`COMFY_BASE_NODES=1`（改 Image）。
