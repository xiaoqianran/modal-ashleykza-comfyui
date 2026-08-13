# 工作流依赖预取

## 目标与边界

工作流必须先于 GPU 部署可用，CPU 才能提前解析和同步依赖。流程不允许在 GPU 启动时下载：GPU 只读取 Image 内的节点和 Volume 内的模型，并执行一次快速存在性检查。

如果用户在已经运行的 ComfyUI 页面里临时上传一个全新工作流，服务端事先不知道该工作流，无法“回到 CPU 阶段”补依赖。正确做法是先在本地拿到 JSON / PNG，运行预取，再部署或重启 GPU endpoint。

## 两阶段命令

```bash
modal run comfyui_modal.py \
  --action hydrate \
  --workflow path/to/workflow.json

COMFY_WORKFLOW_LOCK=path/to/workflow.lock.json \
modal deploy comfyui_modal.py
```

第一条命令在本地解析文件，然后调用 CPU hydrate，把模型并行写入 `comfyui-ashleykza-models` Volume。第二条命令构建 Runtime Image；锁定的 CNR 节点在 Image build 中安装。默认复用 Image 缓存；只有 `COMFY_LATEST=1` 才强制重克隆 GitHub / Registry。模型路径映射见 [`STORAGE.md`](STORAGE.md)。

## 解析规则

解析器遍历普通 ComfyUI `nodes`、嵌套子图，以及 API prompt 的 `class_type` 节点。

模型声明来自根级或节点级 `models` 数组，标准字段如下：

```json
{
  "name": "vendor/model.safetensors",
  "url": "https://huggingface.co/org/repo/resolve/main/model.safetensors",
  "directory": "models/checkpoints",
  "hash": "可选的64位SHA256",
  "hash_type": "SHA256"
}
```

节点声明来自：

```json
{
  "cnr_id": "comfyui-example",
  "ver": "1.2.3"
}
```

解析器还会扫描 widget / API input 中常见模型后缀。只找到文件名而没有 URL 时，项目把它记为 `unresolved`，而不是猜下载源。

## 锁文件

锁文件 schema 1 包含：

- 原工作流文件名和 SHA256；
- 规范化模型目标、HTTP(S) URL、可选 SHA256；
- CNR id、版本和使用它的节点类型；
- 无法解析的文件名引用。

锁文件可提交 Git，便于审查来源和重现部署。它不包含访问 token；认证只从 Modal Secret 注入。

当缺失模型元数据时，可手工补全：

```json
{
  "category": "checkpoints",
  "filename": "vendor/model.safetensors",
  "url": "https://example.com/model.safetensors",
  "sha256": null,
  "source": "manual"
}
```

把对象加入 `models` 后，删除 `unresolved` 中对应条目。校验器会拒绝绝对路径、`..`、重复目标、非 HTTP(S) URL、非法 CNR id 及非 SHA256 哈希。

## 幂等与一致性

- 同步结果记录在 `/mnt/comfy-storage/.state/comfy.lock.json`；
- 有 SHA256 时按哈希验证，无哈希时按 URL 与文件大小复用；
- 每完成一个模型就原子更新状态锁，长任务中断后可以继续；
- Function 成功后显式提交 Volume；
- CPU 同步和 GPU endpoint 都限制为一个容器，避免共享可变 workspace 的并发写冲突；
- GPU Image 内嵌工作流锁，启动前检查所有声明文件存在且非空。

Modal Volume 对已运行容器采用快照式可见性。不要一边让 GPU 写 workspace，一边调用 `reload()`；完成同步后用新部署 / 新容器加载提交后的状态。

## 不能自动解决的情况

- 工作流只有本地文件名，没有 URL；
- custom node 缺少 CNR 元数据且不在 Recipe；
- 下载必须执行网页交互或自定义授权流程；
- 模型由节点运行时动态计算名称；
- 工作流依赖的基础 ComfyUI 版本与当前 Image 不兼容。

这些情况需要先补锁文件或 Recipe。GPU 端不会回退到在线安装。
