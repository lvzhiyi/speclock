# SpecLock (workflow-core 0.25.1) — 修复聊天定档 Markdown 容错、钩子活跃自检与宿主无关通道

- **聊天确认口令兼容成对 Markdown 与引号包裹**：`host_gate.normalize_chat_reply` / `parse_chat_confirmation_reply` 在严格匹配 `选轻量档`、`选标准档`、`选完整档` 与 `批准方案` 前，自动剥离首尾成对包裹（`**`、`__`、`*`、`_`、`` ` ``、`「」`、`『』`、`“”`、`‘’`、`""`、`''`、`【】`）及空白字符，同时保持对自然语言句子、疑问句与未成对标记的拒绝边界。
- **会话级 Hook 活跃自检与 `ENGINE_HOOK_INACTIVE` 诊断告警**：`workflow_gate.handle` 与 `cursor_gate.handle` 在受管项目钩子触发时通过 `host_gate.record_hook_activity` 以 best-effort 方式记录当前会话状态到 `.speclock/hook-session-*.json`（不阻断主门禁、未接入项目继续旁路）；`prepare --request-tier` 与 `request-confirmation` 返回 `hook_active`、`hook_events`、`hook_host` 与 `hook_warning` 诊断字段，并在未检测到 `UserPromptSubmit` / `beforeSubmitPrompt` 回调时给出针对宿主的启用/信任指引或终端确认路径，避免让用户反复重发聊天口令。
- **宿主无关聊天确认通道与旧通道向后兼容**：`request_chat_confirmation` 写入统一 `chat:` 通道，不再因命令行漏传 `WORKFLOW_HOST` 静默写错通道；`chat_confirmation` 优先读取统一 `chat:` 通道，并在缺失时兼容回退旧版 `<host>:chat:` 文件。
- **技能引导与回归测试补齐**：同步更新 `workflow/SKILL.md` 与 `docs/development/workflow-engine.md`，并在 `test_host_gate.py`、`test_workflow_gate.py`、`test_cursor_gate.py`、`test_state_dir.py` 中补充对应单元测试与端到端集成回归。
