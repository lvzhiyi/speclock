# SpecLock (workflow-core 0.28.7) — 完整档窗口审批前置生成审阅稿并强制展示完整方案

- **原生审批卡片前置门禁校验**：在 `host_gate.py` 中对完整档窗口审批（`request_user_input`、`request_user_input_async`、`AskUserQuestion`、`ExitPlanMode`）新增前置检查。未满足方案/步骤/验证配置就绪时返回 `ENGINE_APPROVAL_NOT_READY`；未通过 `render-md --save` 导出与当前版本及 `control_digest` 匹配的 `.speclock/reviews/` 只读审阅稿时返回 `ENGINE_APPROVAL_REVIEW_REQUIRED`（保持工作区零污染、不自动弹出外部窗口）。
- **聊天确认通道内联审阅内容**：`request-confirmation --kind approval` 在登记请求时自动生成只读 Markdown 审阅稿，并在响应中内联返回 `review_path`、`review_display_path`、`review_markdown` 与 `presentation_note`。
- **`render-md` 与技能约束强化**：在 `review_markdown.py` 补充 `non_goals` 渲染及审阅文件校验助手；在 `workflow_engine_cli.py` 的 `render-md --save` 输出中提示展示完整方案正文；同步更新 `tiering`、`workflow`、`kickoff` 技能与 `workflow-engine.md`，要求在聊天回复正文中完整展开提案、技术设计、范围/非目标、影响/风险/回滚、验收、步骤、验证计划及审阅稿路径，禁止浓缩为一两句概括。
- **回归测试补充**：更新并新增 `test_review_markdown.py`、`test_host_gate.py`、`test_workflow_gate.py` 与 `test_cursor_gate.py` 回归用例。
