# SpecLock (workflow-core 0.25.2) — 修复任务 `scope` 前置路径校验缺失

- **引擎入口强制校验顶层 `scope` 为仓库相对路径列表**：`protocol.validate_scope` 在 `create`、`adopt_protocol` 与 `update_task` 时校验 `scope`，拒绝字符串、绝对路径、`..` 越界、反斜杠/通配符（`*`/`?`）、含空白或句读标点的文本，以及磁盘上不存在的单段纯中文业务描述，避免错误 `scope` 绕过定档与方案批准、直到进入 `implementing` 写文件时才被 `host_gate` 拦截并导致已确认回执全部失效。
- **技能引导明确区分路径范围与业务范围**：更新 `tiering/SKILL.md` 与 `workflow/SKILL.md`，明确顶层 `scope` 仅填写仓库相对路径/目录前缀列表，业务范围描述写入 `goal` 或 `proposal.scope`。
- **测试补齐与适配**：在 `test_protocol.py` 新增 `test_scope_must_be_repo_relative_paths` 覆盖非法与合法 `scope` 场景，并将 `test_protocol.py`、`test_cli.py` 中的占位 `['代码']` 调整为路径形式。
