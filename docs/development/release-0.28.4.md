# SpecLock (workflow-core 0.28.4) — 强制 Codex 同步确认弹窗并兼容推荐后缀

- **拦截 Codex 异步确认避免弹窗闪退**：在 `host_gate.py` 中对携带 `workflow-confirm:` 的 `request_user_input_async` 返回 `ENGINE_CONFIRMATION_SYNC_REQUIRED`，强制改用同步阻塞的 `request_user_input`（或降级 `request-confirmation` 聊天回复），彻底解决异步弹窗在模型继续执行或结束回合后自动消失的问题；普通无标记提问保持放行。
- **原生单选标签兼容推荐后缀**：`host_gate.py` 新增 `_strip_recommended_suffix` 与 `is_approval_accept_label`，定档与方案批准单选卡片及回执均兼容 `(Recommended)` / `（推荐）` / `(推荐)` 后缀，同时保持聊天口令严格匹配边界不变。
- **技能指引补强与回归测试**：更新 `workflow`、`kickoff` 技能与 `docs/development/workflow-engine.md`，明确 Codex 仅使用同步阻塞 `request_user_input`，并要求 `hooks.hook_active` 为 `false` 时必须先写明宿主重新信任钩子并新开会话的步骤（不得省略授权指引只给终端命令）；更新 `test_workflow_gate.py` 与 `test_host_gate.py` 回归覆盖。
