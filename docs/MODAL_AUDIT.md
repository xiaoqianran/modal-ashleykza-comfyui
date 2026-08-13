# Modal 1.5 架构审计

审计日期：2026-08-13。SDK 固定为 `modal==1.5.4`，依据 Modal 官方 [`llms.txt`](https://modal.com/llms.txt) 所列当前文档。

## 已采用的官方模式

| 主题 | 仓库实现 | 采用原因 |
|---|---|---|
| Image 分层 | 固定基础镜像；每个稳定节点 / CNR 节点独立 build layer | 稳定层优先，变化层后置，提高缓存复用 |
| 本地模块 | `add_local_python_source(...)` | Modal 1.x 不再隐式挂载任意本地模块 |
| 构建期文件 | 锁文件 `add_local_file(..., copy=True)` | 后续构建与运行均可读取固定副本 |
| 大模型权重 | CPU Function 下载到 Volume | 避免把大权重烘焙进 Image，也不占 GPU 下载时间 |
| Volume 持久化 | 同步完成后显式 `workspace_vol.commit()` | 明确发布 CPU Function 的写入 |
| 下载重试 | `modal.Retries` 指数退避 | 处理临时网络 / 上游错误，避免紧密重试 |
| 资源声明 | 同步使用 2 CPU / 2048 MiB；UI 显式 GPU fallback | 容量和成本可预期 |
| 超时 | UI 最大 24 小时；独立 `startup_timeout` | 遵守 Function 超时上限并给大 Image 冷启动留时间 |
| 并发 | `max_inputs` 与 `target_inputs` 可配置 | WebSocket / HTTP 并发有上限，扩容阈值明确 |
| 缩容 | `scaledown_window` 可配置 | 在冷启动成本和空闲 GPU 成本之间取舍 |
| Web 认证 | 可选 `requires_proxy_auth` | 保留浏览器兼容，同时提供 Modal 代理认证开关 |

官方参考：

- [Images and build cache](https://modal.com/docs/guide/images)
- [Model weights](https://modal.com/docs/guide/model-weights)
- [Volumes](https://modal.com/docs/guide/volumes)
- [Retries](https://modal.com/docs/guide/retries)
- [Timeouts](https://modal.com/docs/guide/timeouts)
- [Concurrent inputs](https://modal.com/docs/guide/concurrent-inputs)
- [Web endpoint proxy authentication](https://modal.com/docs/guide/webhook-proxy-auth)

## 关键取舍

### 保留 `web_server`，不改为 Server primitive

ComfyUI 已经是完整的长驻 HTTP / WebSocket 服务。`@modal.web_server` 直接表达该运行模型，并提供启动探测、代理 URL 与认证选项。Server primitive 更适合需要端口级客户端、TLS 隧道或非 HTTP 协议的服务；当前迁移没有足够收益。

### 单一 workspace Volume

模型、输入、输出和用户状态继续使用同一已有 Volume，避免迁移时丢失用户数据。代价是不能把模型挂载单独设为只读。通过单容器限制、同步前置和显式 commit 降低冲突风险；未来若做破坏性存储迁移，再拆分只读 model Volume 与可写 user Volume。

### 一个 GPU 容器

ComfyUI 的队列和可变用户目录不是无状态服务。即使 `@modal.concurrent` 接收多个连接，也将 `max_containers=1`，避免多个 GPU 容器对同一 workspace 同时写入。需要横向扩展时，应先把队列、输出命名和用户状态改成多租户安全设计。

### 公开 endpoint 保持兼容默认

`requires_proxy_auth=True` 需要客户端添加 Modal 认证头，普通浏览器直接访问不方便。因此默认保持 `false`，但把开关暴露为配置。生产部署者必须基于访问方式决定反向代理、Modal 代理认证或其他网络边界。

## 版本与升级策略

- Modal、comfy-cli、huggingface-hub 和 CI 工具都精确固定版本；
- SDK 或基础 ComfyUI Image 升级应独立 commit，不与 Recipe 变更混合；
- 升级后至少运行 compileall、全部 unittest 和 Ruff；
- 先在 `modal serve` 验证构建、Volume 挂载、WebSocket 和一个真实工作流，再发布 `modal deploy`。
