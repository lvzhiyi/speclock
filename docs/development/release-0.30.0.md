# SpecLock (workflow-core 0.30.0) — 新增 `grill-me` 式需求澄清技能 `clarify` 并收敛 `PreToolUse` 本地写入边界

- **新增 `clarify` 深度需求澄清技能与规划门禁**：
  - 新增 `plugins/workflow-core/skills/clarify/SKILL.md`：面对协作状态为「待确认」、含未决 `- 待确认：` / `Qxx` 项或目标/范围/验收模糊的任务卡，先在仓库文档、源码、设计与契约中自查事实，再沿决策树逐枝追问、给出推荐答案与依据，严禁携带 `workflow-confirm:` 混入授权链；收敛共识后按文档职责回写任务卡与产品文档，阻塞全清时流转为 `待处理`（不误勾完成框）。
  - 扩展 `workflow_planning_cli.py` 与 `host_gate.py`：支持 `--operation clarify`（仅限配置产品文档角色与 `docs.cards_dir` 直接模块卡，禁止改写配置、入口文件与开发规范），并在 `init_read_command` 中同步放行只读 `check_docs.py --root <项目根>`（可选 `--check-config`）。
  - 联动 `workflow`、`kickoff`、`prd-breakdown`、`workflow-engine.md`、`README.md` 与 `README.zh-CN.md`，并在 `examples/speclock-codex-test` 新增英文待澄清示例任务卡 `AUTH-R04`。
- **`PreToolUse` 同步门禁收敛至本地仓库写入边界**：
  - 更新 `host_gate.py`，仅对本地仓库写入边界（原生编辑工具、写入本地仓库或 `.speclock/` 的 MCP 工具、可能修改本地仓库或执行任意脚本/解释器的 Shell 命令与 `Task` 委派）执行任务就绪检查；直接放行外部非本地写入型调查工具（如 Pixso / Apifox 查询 / 浏览器工具及只读 CLI 管道），避免阻塞定档与方案准备前的外部契约或设计调研。同步更新 `workflow-engine.md` 与 `cursor-adapter.md`。
- **多宿主回归与契约测试**：
  - 新增 `test_clarify_skill_contract.py`，并扩充 `test_planning_gate.py`、`test_cursor_gate.py`、`test_host_gate.py`、`test_workflow_gate.py` 与 `test_state_dir.py` 回归覆盖。
