# SpecLock (workflow-core 0.30.1) — 补齐中英文结构化待确认记录解析与校验

- **Dashboard 支持双语结构化待确认记录提取**：
  - `dashboard_data.py` 新增 `_parse_pending()`，统一解析中文 `- 待确认：…｜影响：…｜恢复条件：…` 与英文 `- Pending (Q01): ... | Impact: ... | Resume when: ...`（兼容 `Pending:` / `Pending Clarification:`、`Resume:` / `Resume condition:`、`Owner:`、`Source:` 及半角/全角竖线），保留可选问题编号（如 `Q01: ...`）并在字段缺失时报告 `待确认记录字段不完整：`。
- **`check_docs.py` 与示例项目脚本同步校验**：
  - `check_docs.py` 新增 `check_pending_line()` 校验中英文结构化待确认记录的必填字段，并保持对无竖线自由文本的兼容；同步通过 `vendor_check_docs.py` 重新导出 `examples/speclock-codex-test/scripts/check_docs.py`。
- **技能规范与回归测试补齐**：
  - `prd-breakdown/SKILL.md` 与 `clarify/SKILL.md` 并列写明中英文结构化待确认格式。
  - 在 `test_dashboard_data.py`、`test_check_docs.py` 与 `test_clarify_skill_contract.py` 补充英文结构化待确认记录解析、校验及技能契约回归测试。
