# SpecLock (workflow-core 0.26.1) — 兼容 Codex `request_user_input_async` 原生单选卡片

- **识别并放行 Codex `request_user_input_async`**：在 `host_gate.py` 中将 `request_user_input_async` 纳入 Codex 原生确认工具白名单，避免其落入写门禁被 `ENGINE_NOT_READY` 拦截；普通无标记提问自动放行。
- **适配 `request_user_input_async` 参数与回执**：支持 `title` 题干、无 `id` 结构以及字符串数组 `options`（同时兼容 `轻量档`/`标准档`/`完整档` 与 `选轻量档`/`选标准档`/`选完整档`）；调用时同步登记聊天通道等待凭据，既支持 `PostToolUse` 同步回执，也支持 `PostToolUse` 返回异步确认后由 `UserPromptSubmit` 自动消费用户点选结果。
- **技能与测试**：更新 `workflow/SKILL.md` 说明，并在 `test_workflow_gate.py` 新增 `test_codex_request_user_input_async_tier_and_approval` 覆盖定档与方案批准全链路。
