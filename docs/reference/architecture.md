# 架构

```text
comfyui_modal.py      GPU App：Cls UI + web_server
hydrate_modal.py      CPU App：hydrate / resolve / profiles
modal_config.py       常量、路径、环境变量
storage.py            Volume 路径与 extra_model_paths.yaml
comfy_engine.py       下载、校验、启动 ComfyUI
workflow_resolver.py  工作流 → 锁文件
recipes.py            profile / model pack / node pack
base_nodes.py         基础自定义节点安装
examples/             示例 workflow / lock
docs/                 本站点 Markdown
mkdocs.yml            MkDocs Material 配置
```

## GPU 类

`UI`（`comfyui_modal.py`）：

- `enable_memory_snapshot=True`（可用 `COMFY_MEMORY_SNAPSHOT=0` 关闭）
- `experimental_options={"enable_gpu_snapshot": True}`（可用 `COMFY_GPU_SNAPSHOT=0` 关闭）
- `@modal.enter(snap=True) start()`：读 Volume launch.json、校验模型、`prepare_runtime`、按需把 CNR 装到 workspace、启动 ComfyUI、等待就绪
- `@modal.web_server ui()`：空方法，端口已在 listen
- `@modal.exit() stop()`：`commit()` workspace Volume，再终止 ComfyUI
- `@modal.concurrent` + `max_containers=1`

不要根据 `sys.argv` 决定是否注册 `ui`。远程容器里的 argv **不是** `modal serve`，否则会得到 `App has no function 'ui'`。

## Image 分层

默认 Image 对所有工作流相同，才能吃到 Modal 层缓存：

1. 固定 Ashley 基础镜像
2. apt + `typing_extensions` / `pydantic`
3. 固定 `comfy-cli==1.16.0`（给运行时装 Volume 插件用）
4. `COMFY_BASE_NODES=1`：约 130 个 GitHub 节点（默认关，会改 Image）
5. `COMFY_INSTALL_NODES=1`：profile 额外 node packs（默认关，会改 Image）

工作流锁里的 CNR **不在 Image 里**。hydrate 写入 `.state/launch.json`，GPU 启动时装到 `/workspace/custom_nodes`。

`COMFY_LATEST=1` 才会强制重建节点层。

## Volume 提交

CPU Function 在成功路径调用 `models_vol.commit()` 与 `workspace_vol.commit()`。GPU 在首次把 CNR 写入 `/workspace/custom_nodes` 后也会 `workspace_vol.commit()`，否则缩容后下次还会再装一遍。SaveVideo 写入 `/workspace/output` 后由后台 watch 再 `commit()`；`@modal.exit()` 再提交一次。成片不需要 GPU 容器继续活着，用 hydrate CPU `--action outputs` 或 `modal volume get` 读取。

## Volume 路径

所有路径由 `storage.py` 规范化：去掉重复的 `models/`、category、`output/` 前缀；hydrate 与 GPU 启动时摊平已套层的目录。成片只在 workspace Volume 的 `/output`。
