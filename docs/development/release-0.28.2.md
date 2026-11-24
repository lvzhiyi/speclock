# SpecLock (workflow-core 0.28.2) — 看板支持四级子任务与已验收状态优先并自动收口旧实施记录

- **看板支持四级子任务标题与子任务完成勾选**：扩展 `dashboard_data.py` 的 `CARD` 正则支持 `###` 与 `####`（如 `#### AUTH-R07-T1 ...`），复选框正则同时识别 `- [x] 子需求完成` 与 `- [x] 子任务完成`（及人工验收勾选），避免四级子任务在看板侧漏解析。
- **已验收任务卡不被本机旧实施状态覆盖**：调整 `_engine` 合并优先级，当 Git 任务卡已是 `completed`（已验收 / 已完成 / 已交付 / `[x]`）时，绝不再被本机任何旧记录（含停留在 `implementing` 的历史会话）覆盖；任务卡已是 `review_passed` 时，本机无完成步骤且无验证尝试的 `created` / `implementing` 也不再覆盖它。
- **对账自动收口已验收或 0 步实施的旧记录**：扩展 `protocol.py` 的 `_card_closure`，当任务卡已由人工确认结案（`已验收 / 已完成 / 已交付 / [x]`）或本机停留在 `created` / `implementing` 且尚无已完成步骤与验证尝试时，直接标记 `auto_close` 并自动收口为 `cancelled`（`card_superseded`）；仅「评审通过，待人工验收」且本机已有完成步骤或验证尝试时才报 `needs_decision` 交由人工决定。
