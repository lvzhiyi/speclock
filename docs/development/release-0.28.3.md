# SpecLock (workflow-core 0.28.3) — 前置检查 SpecLock 钩子授权状态

- **新增只读前置检查入口 `check-hooks` 并内联入口诊断**：在 `workflow_engine_cli.py` 新增不依赖任务或状态库的纯只读 `check-hooks [--session SESSION]` 命令（绝不创建 `.speclock/` 也不触发旧库迁移），并在 `list`、`status`、`prepare`、`bind-executor`、`resume` 响应中统一内联返回 `hooks` 状态字段（其中 `list` / `status` / `resume` 同步支持可选 `--session`）。
- **精准识别未授权钩子与会话错配**：在 `host_gate.py` 新增 `resolve_cli_session` 与 `hook_precheck_status`，按「显式 `--session` > `CODEX_THREAD_ID` / `CLAUDE_SESSION_ID` > 任务当前轮次绑定」解析会话，避免旧任务沿用历史会话记录产生假阳性；未检测到当前会话钩子但存在其他会话近期记录时标记 `other_active_sessions: true` 并提示核对 `--session`，无会话 ID 且存在历史记录时返回 `ENGINE_HOOK_SESSION_UNKNOWN`；告警文案同步明确原生单选卡片与聊天回复均依赖钩子运行。
- **技能前置拦截与回归测试**：更新 `workflow`、`kickoff`、`tiering` 技能及 `docs/development/workflow-engine.md`，要求在调用原生单选卡片（`request_user_input` / `request_user_input_async` / `AskUserQuestion`）或聊天口令确认前必须核对 `hooks.hook_active == true`，未激活时第一时间引导宿主授权并新开/重启会话或改用终端确认；在 `test_host_gate.py`、`test_workflow_gate.py`、`test_state_dir.py` 补充完整单测与集成覆盖。
