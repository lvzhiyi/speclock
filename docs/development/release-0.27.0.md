# SpecLock (workflow-core 0.27.0) — 任务卡结案自动对账与未开工任务自动关闭

- **任务卡结案自动对账（`close_superseded` / `reconcile_cards`）**：当任务卡已处于结案状态（「评审通过，待人工验收 / 已验收 / 已完成 / 已交付」或卡内完成框已勾选 `[x]`），而本机 SpecLock 同名任务仍未开工（`state == 'created'`、无尝试记录、无已完成步骤）时，引擎自动将本地记录关闭为 `cancelled`（记录 `card_superseded` 证据与 `cancel.reason='card_superseded'`），无需人工手动 `cancel`。
- **显式绑定优先与唯一标题兜底匹配**：优先按任务 `details.card` 对账；未绑定任务仅在配置的 `docs.cards_dir` 直接子级 `*.md` 中恰好唯一命中一处 `### <task_id>` 标题时匹配，出现歧义则不自动关闭。已开工任务（`implementing` 等）不自动关闭，只读 `status` 展示 `card_closure.action='needs_decision'` 并输出冲突提示交由人工决定。
- **全入口触发与测试覆盖**：在 `SessionStart` 钩子（Claude Code / Codex / Cursor）、CLI `prepare` / `begin` / `resume` 执行前自动触发对账，并新增 CLI `reconcile-cards` 子命令；在 `tests_engine/test_card_reconcile.py` 新增 10 项测试覆盖自动关闭、唯一标题匹配、已开工冲突保护、幂等与钩子通知。
