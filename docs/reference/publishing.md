# 文档站点

本站点用 [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) 构建，经 GitHub Actions 发布到 GitHub Pages。

线上地址：<https://xiaoqianran.github.io/modal-ashleykza-comfyui/>

## 本地预览

```bash
python -m pip install -r docs/requirements.txt
mkdocs serve
```

严格构建（与 CI 相同）：

```bash
mkdocs build --strict
```

源文件在 `docs/`，导航在仓库根目录 `mkdocs.yml`。

## Actions 发布

工作流 [`.github/workflows/docs.yml`](https://github.com/xiaoqianran/modal-ashleykza-comfyui/blob/main/.github/workflows/docs.yml) 遵循 GitHub 官方 Pages 流程：

1. `push` 到 `main`（或手动 `workflow_dispatch`）
2. `mkdocs build --strict` 产出 `site/`
3. `actions/upload-pages-artifact`
4. `actions/deploy-pages@v4` 发布到 `github-pages` environment

仓库 **Settings → Pages → Source** 必须选 **GitHub Actions**（不要用 `gh-pages` 分支）。第一次部署若环境不存在，Actions 会创建 `github-pages`；若 404，到 Settings 里确认 Source。

CI（`.github/workflows/ci.yml`）也会跑 `mkdocs build --strict`，避免未通过的文档合入 `main`。

## 两块站点：文档 + 图库

顶栏 tab 始终同时显示文档和 **图库**（`navigation.tabs.sticky`，滚动也不消失）：

| Tab | 内容 | 来源 |
|---|---|---|
| 首页 / 指南 / 参考 / … | 本仓库 MkDocs | `docs/`，进 git |
| 图库 | 生成图 / 视频 / 3D | 私有 HF 数据集，**不进 git** |

图库是和首页同级的导航项，不是文档下面的子页，所以从文档点进去、再点回来都在顶栏。

数据集：[`seachen/modal-comfyui-picture`](https://huggingface.co/datasets/seachen/modal-comfyui-picture)

```text
image/     图片模型（t2i / i2i）
video/     视频模型（t2v / i2v）
mesh3d/    3D 模型（i23d）
  <recipe-id>/
    <collection-id>/
      collection.json
      001.png
      001.json    # 提示词 sidecar
```

Actions 每小时（`cron: 0 * * * *`）用 `HF_TOKEN` 拉取数据集，生成 `docs/gallery/_generated.md` 和缩略图，再 `mkdocs build`。仓库 Settings 需要 secret **`HF_TOKEN`**（Hugging Face 写/读权限）。没有这个 secret 时文档仍能发布，图库显示占位说明。

有 token 时工作流会跑 `python -m gallery_hub.report --require-items`：打印 `collections=` / `items=`，并在拉到 0 件时失败，避免空图库覆盖线上。数据集布局是 `image|video|mesh3d/<recipe>/<collection>/`。

推送一批新作品（本机，不经过 git）：

```bash
python -m gallery_hub.push \
  --recipe flux2-dev --kind t2i --collection campus-days \
  --timings artifacts/campus-days-flux2/timings.json
```

注意：HF 数据集是私有的，但编进 GitHub Pages 的快照是**公开**的。不要上传不能公开的文件。

