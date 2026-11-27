# SpecLock (workflow-core 0.31.0) — 默认英文文档骨架与检查脚本，并优化看板沙盒提权诊断

- **看板沙盒/权限诊断与宿主提权指引**：
  - `dashboard_server.py` 区分 `EADDRINUSE` 与沙盒/权限错误（`code=SANDBOX_OR_PERMISSION`），改用 `ProxyHandler({})` 直连 `127.0.0.1`，通过启动管道透传子进程失败原因并在回环校验受阻时清理孤儿进程；`status`/`off` 在回环受阻时保留状态文件，不再误报 `OFF`。
  - `dashboard/SKILL.md` 引导在 `SANDBOX_OR_PERMISSION` 场景优先走宿主原生单次命令提权审批（如 Codex `require_escalated`），仅在不支持或用户拒绝时退回终端命令。
- **默认英文文档骨架与自包含检查脚本**：
  - `templates/` 默认提供英文 `ai-workflow.yaml`、`task-card.md`、`handoff.md`、`blocked.md` 与 `docs/` 文档骨架；原中文模板完整保留至 `templates/zh/`。
  - `workflow_config.py`、`check_docs.py` 与 `vendor_check_docs.py` 输出英文诊断与导出头，支持英文占位符（`TBD` / `N/A` / `none`）与英文术语表 `- Definition:`，同时保持对中文文档、`来源：workflow-core ` 旧导出头、`workflow_planning_cli.py` 与 `review_card.py` 中英文默认路径的向后兼容。
  - `init`、`prd-breakdown`、`handoff`、`verify` 技能更新为默认英文，按项目已有文档语言或用户偏好选用 `en` / `zh` 模板。
