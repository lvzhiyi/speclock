# SpecLock (workflow-core 0.26.0) — 原生单选卡片支持方案批准并优先点选

- **原生单选组件支持完整档方案批准**：扩展 `host_gate.py` 的 `prepare_confirmation` 与 `complete_confirmation`，使 Claude Code 的 `AskUserQuestion` 与 Codex 的 `request_user_input` 同时支持 `tier_confirmation`（定档）与 `approval`（方案批准）。方案批准单选强制要求包含当前 `workflow-confirm:<task>:<round>:<digest>:approval` 标记、禁用多选与预填 `answers`、提供至少两个不重复选项（含 `批准方案` 及至少一个不批准项）；仅当用户选中 `批准方案` 时落库，选中不批准项或重放旧回执均拒绝。
- **技能引导优先原生点选，聊天口令仅作降级兜底**：更新 `workflow/SKILL.md`、`kickoff/SKILL.md` 与 `docs/development/workflow-engine.md`，要求在当前会话具备原生单选工具时，定档与方案批准均优先使用宿主单选卡片，不再默认走 `prepare --request-tier` 要求用户手打口令；仅在宿主/会话缺少原生单选工具（如 Cursor 或未暴露 `request_user_input` 的会话）时回退为聊天口令。
- **测试覆盖**：在 `test_host_gate.py` 与 `test_workflow_gate.py` 新增原生单选批准校验与端到端测试，覆盖 Codex `request_user_input` 与 Claude Code `AskUserQuestion` 的正常批准、单选项拦截、不批准拒绝及回执重放拦截。
