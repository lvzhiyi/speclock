# SpecLock (workflow-core 0.24.0) — 交互确认 Markdown 审阅弹窗、简洁回执与 `render-md` 导出

- **交互确认前生成并弹出 Markdown 审阅稿**：`approve-proposal`、`confirm-tier`、`confirm-plan`、`return-task` 在交互终端提示输入 `confirm` 前，自动将任务元信息、目标、完整档 `proposal`（设计/范围/影响/风险/回滚/验收）、实施步骤、检查计划及门禁状态渲染为结构化 Markdown，原子写入项目外引擎状态目录 `<db_dir>/reviews/`（`0o700` 目录、`0o600` 文件，零工作区污染），并按当前宿主环境（`cursor` / `code` / `open` / `xdg-open`）非阻塞弹出审阅，失败或传 `--no-open` / `WORKFLOW_NO_OPEN=1` 时自动回退为终端内完整 Markdown 展示。
- **交互确认后输出简洁 Markdown 回执**：在交互终端（TTY）完成确认后，默认向 `stdout` 输出简洁可读的 Markdown 登记回执（含任务 ID、最新版本号、状态、控制摘要、进度与下一步提示），不再刷屏单行大段 JSON；非 TTY 管道调用或显式传 `--json` 时完整保留既有 JSON 输出契约。
- **新增只读 `render-md` 子命令**：支持 `workflow_engine_cli.py render-md --task <ID> [--save] [--open] [--json]`，可随时只读导出或弹出当前任务的 Markdown 审阅视图，数据库不存在时返回 `NOT_FOUND` 且不创建状态库。
- **单元测试与真实 PTY 集成测试**：新增 `test_review_markdown.py`，覆盖 Markdown 渲染（含 v2 完整档、legacy v1、版本/摘要不一致提示、表格转义）、项目外安全写盘与符号链接拦截、打开器探测降级，以及基于 `pty.openpty()` 的真实终端确认闭环。
