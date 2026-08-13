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
- `@modal.enter(snap=True) start()`：校验锁文件中的模型、`prepare_runtime`、启动 ComfyUI、等待就绪
- `@modal.web_server ui()`：空方法，端口已在 listen
- `@modal.exit() stop()`：终止进程
- `@modal.concurrent` + `max_containers=1`

不要根据 `sys.argv` 决定是否注册 `ui`。远程容器里的 argv **不是** `modal serve`，否则会得到 `App has no function 'ui'`。

## Image 分层

稳定层在前、变化层在后，以便复用构建缓存：

1. 固定 Ashley 基础镜像
2. 可选的基础 GitHub 节点（`COMFY_BASE_NODES`）
3. profile 额外节点
4. 锁文件里的 CNR 节点（`add_local_file(..., copy=True)` 打进 Image）

本地 Python 模块通过 `add_local_python_source(...)` 注入（Modal 1.x 不再隐式挂载任意本地模块）。

`COMFY_LATEST=1` 才会强制重克隆节点层；默认 serve / deploy 复用缓存。

## Volume 提交

CPU Function 在成功路径调用 `models_vol.commit()` 与 `workspace_vol.commit()`。GPU 只读模型目录；用户输出写在 workspace Volume。
