> 🌐 Language / 语言：**中文版** · [English](./AGENTS.md)

# 仓库规范

- 分支名和 Pull Request 标题中不得包含 `codex`。
- 除非用户明确要求智能体执行合并、并在合并前立即确认，否则不要将 Pull Request 合并到 `main`。审阅、修复、准备、收尾或"让 PR 就绪"等请求均不构成合并授权。PR 就绪后，报告其状态并请求确认；只有在收到明确的后续确认后才执行合并。
- 对于已存在 / 未关闭的 Pull Request，不要做 amend、squash、rebase 改写历史，或强制推送后续改动。除非明确要求改写历史，否则应正常提交并推送。
- 发布类的 Pull Request 应只聚焦于版本号元数据和发布文档。
- 不要提交本地构建产物，例如 `dist/`、`build/`，或生成的 wheel / sdist 文件。

## 发布到 PyPI

PyPI 发布由 GitHub Actions 在 `.github/workflows/publish.yml` 中处理。工作流在推送匹配 `v*` 的标签时触发，使用 `uv build` 构建包，用 `twine check --strict` 检查产物，并通过配置好的 `pypi` 环境发布。

准备发布：

1. 确认目标版本尚未在 PyPI 上发布。
2. 在 `pyproject.toml` 中提升 `version`。
3. 在 `src/speech_to_speech/__init__.py` 中提升 `__version__`。
4. 开启并合并一个仅包含发布准备改动的 Pull Request。

发布 PR 合并后：

1. 本地更新 `main`：`git checkout main && git pull origin main`。
2. 为版本创建带注释的标签：`git tag -a vX.Y.Z -m "Release vX.Y.Z"`。
3. 推送标签：`git push origin vX.Y.Z`。
4. 观察 `Publish` GitHub Actions 工作流成功完成。
5. 确认新版本已出现在 `https://pypi.org/project/speech-to-speech/`。

只有在 GitHub Actions 工作流不可用、且维护者明确选择该回退方案时，才手动上传。
