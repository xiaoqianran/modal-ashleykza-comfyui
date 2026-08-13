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
