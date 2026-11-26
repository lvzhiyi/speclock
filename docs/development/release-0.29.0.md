# SpecLock (workflow-core 0.29.0) — 全面兼容 Claude Code 与 Cursor 最新能力并默认英文看板

- **Claude Code 兼容补强**：
  - `workflow_gate.py` 在 `SessionStart` 中支持将 `WORKFLOW_HOST=claude` 与 `CLAUDE_SESSION_ID` 持久化写入 `CLAUDE_ENV_FILE`（未接入项目保持静默且不创建 `.speclock/`），并在已接入项目向 `additionalContext` 注入 `Claude session_id` 与绝对 CLI 路径，便于 `check-hooks`、`prepare` 与规划登记直接取用真实会话。
  - `host_gate.py` 的 `AskUserQuestion` 兼容英文选项（`Light Tier` / `Standard Tier` / `Full Tier`、`Approve Proposal` / `Approve Plan`、`Confirm`，均支持 `(Recommended)` / `（推荐）` 后缀）、`header` 键映射及字符串 JSON 回执；`PLANNING_EDIT_TOOLS` 补充 `MultiEdit`，`READ_TOOLS` 补充 `ToolSearch`。
- **Cursor 兼容补强**：
  - `cursor_gate.py` 在 `sessionStart` 返回的 `env` 中同时注入 `CURSOR_CONVERSATION_ID`（供 `host_gate.resolve_cli_session` 与 `check-hooks` 自动解析），并在 `PreToolUse` 校验 `StrReplace` 与 `EditNotebook`（支持 `target_notebook` / `notebook_path` 等路径字段）。
  - `host_gate.py` 将 `StrReplace` 纳入规划与实施编辑白名单，将 `SemanticSearch`、`ListDir`、`GlobFileSearch` 纳入只读调查工具，并在 `detect_host()` 中识别 `CURSOR_CONVERSATION_ID`、`CURSOR_AGENT`、`CURSOR_TRACE_ID`；聊天确认与 `workflow_engine_cli.py --tier` 全面支持中英文参数与口令（`light` / `standard` / `full`、`Select ... Tier`、`Approve Proposal`）。
- **默认英文看板与双语工作流支持**：整合 `0.28.8` 之后的英文默认看板页面（保留右上角中文一键切换）、中英文任务卡状态/字段解析与回写（`Status: Review Passed, Pending Human Acceptance`）及双语定档/审批提示，并同步更新 `workflow`、`kickoff`、`init` 技能与 `cursor-adapter.md`、`workflow-engine.md` 文档。
- **仓库自检与回归验证**：修复 `scripts/check.py` 以对齐 `examples/speclock-codex-test/src`，并在 `test_host_gate.py`、`test_workflow_gate.py`、`test_cursor_gate.py` 中补充 Claude Code 与 Cursor 端到端协议回归测试。
