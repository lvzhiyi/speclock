# SpecLock (workflow-core 0.25.0) — 项目内 `.speclock/` 默认状态目录与默认沙箱开箱即用

- **默认状态目录迁入项目内 `<项目根>/.speclock/`**：`state.sqlite`、`confirmation-*.json`、`planning-*.json`、`reviews/` 与 `dashboard.json` 默认统一保存在 `<项目根>/.speclock/`（单项目下 CLI、Hooks 与看板共享同一真相源），消除 Codex `workspace-write` 等默认沙箱下的写权限阻断，无需再手工配置 `writable_roots` 白名单。
- **自包含忽略、快照隔离与门禁保护**：首次写入状态时自动以 `0o700` 创建 `.speclock/` 并以 `O_EXCL | O_NOFOLLOW` 写入内容为 `*\n` 的 `.speclock/.gitignore`（不修改项目根 `.gitignore`）；只读命令缺库时仍不创建目录。`snapshot.py` 硬编码跳过 `.speclock/`，防止状态写入触发 `stale`；`host_gate.py` / `cursor_gate.py` 拦截直接编辑 `.speclock/`（返回 `ENGINE_STATE_PROTECTED`），`workflow_planning_cli.py` 拒绝 `.speclock` 规划目标，符号链接一律报 `DB_LOCATION`。
- **只读备份自动迁移旧版状态库**：未设置 `WORKFLOW_ENGINE_HOME` 且未传入 `--db` 时，若新库尚不存在而旧库 `$CODEX_HOME/workflow-engine/<sha256>/state.sqlite`（默认 `~/.codex/workflow-engine/...`）存在且非符号链接，CLI 与门禁 `load_task` 会通过 `?mode=ro` 与 `sqlite3.backup()` 原子复制到 `.speclock/state.sqlite`（`0o600`），保留原库不删除，并在 stderr 打印一行提示；看板只读查询不触发迁移，仅提示有可迁移旧库。
- **外部模式与不可写诊断兼容**：显式设置 `WORKFLOW_ENGINE_HOME` 或传入 `--db` 仍按项目外目录行为工作。遇到权限不足或只读 SQLite 错误时，CLI 返回 `STATE_NOT_WRITABLE` 与可执行修复指引，并在技能规则中禁止提议用聊天记录代替引擎登记。
- **注意事项**：`git clean -fdx`（不含普通 `git clean -fd`）会清理未跟踪且被忽略的 `.speclock/` 本地状态；多个 Git worktree 拥有独立项目根，各自保留独立状态。跨项目的全局流程度量 `workflow-metrics/records.jsonl` 仍保留在 `$CODEX_HOME` / `~/.claude/`。
