# SpecLock (workflow-core 0.28.8) — 支持 init 规划态安全导出自包含 `check_docs.py`

- **窄口门禁放行 `vendor_check_docs.py`**：在 `host_gate.py` 新增 `vendor_check_docs_command`（Claude Code、Codex、Cursor 三端共用）。`--check <项目内路径>` 与 `--help` / `-h` 独立只读放行；`--output scripts/check_docs.py`（支持相对或当前项目根等价绝对路径）仅在当前会话持有活跃 `operation == "init"` 规划登记时放行，严格拒绝 `--force`、非 `scripts/check_docs.py` 目标、路径穿越、符号链接、`.speclock/` 状态目录与插件源码目录。
- **防误覆盖与符号链接防护**：在 `vendor_check_docs.py` 写入前检查目标是否为符号链接或非常规文件；若目标已存在且头部不含 `来源：workflow-core ` 导出标记，默认拒绝覆盖（仅人工手动传 `--force` 才允许强制覆盖），避免误覆盖消费项目自有的同名脚本。
- **文档与技能同步**：更新 `init` 技能和 `workflow-engine.md` 协议说明，将导出自包含 `scripts/check_docs.py` 明确为初始化时默认推荐、经用户确认后执行且支持更新模式刷新检查的步骤。
- **回归测试补充**：在 `test_vendor_check_docs.py`、`test_planning_gate.py` 与 `test_cursor_gate.py` 中补充防误覆盖、三宿主窄口放行与越界拒绝用例。
