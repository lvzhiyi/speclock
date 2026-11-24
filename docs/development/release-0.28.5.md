# SpecLock (workflow-core 0.28.5) — 恢复 Codex 异步单选弹窗保活与点击回执解析

- **恢复 Codex `request_user_input_async` 原生单选卡片并保活回合**：在 `host_gate.py` 中重新放行合法的 `request_user_input_async` 定档与审批卡片；`PostToolUse` 收到异步接收回执（如 `{"accepted": true}`）时返回 `ENGINE_CONFIRMATION_PENDING` 并明确要求模型调用 `clock.sleep(30000)` 保持当前回合等待点击，避免立刻发送 `final_answer` 导致 Codex 桌面端关闭弹窗。
- **解析 Codex 异步弹窗点击回执 `<send_user_message_question_reply>`**：在 `host_gate.py` 新增 `_parse_async_question_reply` 与 `_async_question_confirmation`，严格校验 `questionItemId` 中的 `call_id`、当前 `workflow-confirm:` 控制摘要标记及选项标签（兼容 `(Recommended)` / `（推荐）` 后缀），直接完成定档或方案批准落库，并拦截错误 `call_id`、不批准选项与重放回执。
- **技能与回归测试同步更新**：更新 `workflow`、`kickoff` 技能与 `docs/development/workflow-engine.md` 说明，并在 `test_host_gate.py`、`test_workflow_gate.py` 补充异步回执解析与端到端回归测试。
