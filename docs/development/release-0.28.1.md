# SpecLock (workflow-core 0.28.1) — 修复四级子任务标题导致父任务卡状态回写误拒问题

- **修复任务卡章节边界识别**：将 `review_card.py` 的 `HEADING` 正则由 `#{1,3}` 扩展至 `#{1,6}`，当父任务 `### <card_id>` 下存在四级子任务标题 `#### <sub_id>` 时，扫描遇到子任务标题即终止父任务段落，不再把子任务的 `- 协作状态` 或 `- [x]` 误计入父任务而触发 `CARD_INVALID` / `CARD_CONFLICT`。
- **支持四级子任务直接定位与回写**：`_scan` 与 `find_card` 同时支持匹配 `### <id>` 与 `#### <id>` 任务卡，并补充 `test_level4_subtask_heading_stops_parent_scan_and_supports_direct_subtask_writeback` 回归测试。
