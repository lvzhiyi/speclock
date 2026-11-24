# SpecLock (workflow-core 0.28.6) — 放行 Codex `clocksleep` 等等待保活工具避免异步弹窗被拦截关闭

- **放行无写入等待/保活工具**：在 `host_gate.py` 的 `READ_TOOLS` 白名单中纳入 `clocksleep`、`clock.sleep`、`clock:sleep`、`clock__sleep`、`sleep` 与 `wait`，修复 Codex 调用 `clock.sleep(30000)` 保持异步定档/审批弹窗活跃时被 `PreToolUse` 误判为未授权写入（`ENGINE_NOT_READY`）拦截的问题。
- **回归测试补充**：在 `test_host_gate.py` 与 `test_workflow_gate.py` 补充未定档状态下对上述等待工具放行的回归用例。
