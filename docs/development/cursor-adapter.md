# Cursor 适配（0.30.1）

本仓库仅为 `workflow-core` 提供 Cursor 原生插件清单。根 `.cursor-plugin/marketplace.json` 只列该插件，其他维度插件、组合包和外部依赖不承诺可在 Cursor 安装。本版本提供远程仓库发布内容；安装与启用需通过 Cursor 支持的插件入口完成，不直接修改用户全局配置。

## 安装与检查

需要支持插件和 hooks 的 Cursor 版本、Python 3、Git。通过 Cursor 插件安装入口从本仓库添加 marketplace，再选择 `workflow-core`；本地开发可将 `plugins/workflow-core` 作为插件目录加载。具体入口以当前 Cursor 版本为准，本适配未验证真实客户端安装，不提供臆测的 CLI 安装命令。重启会话后检查技能可发现、sessionStart 返回宿主环境以及 preToolUse 是否执行，并通过 `check-hooks` 核对 `hooks.hook_active`；未实际执行的钩子不能算覆盖。

清单使用 `hooks: "./hooks/cursor.json"`、`skills: "./skills/"`。Cursor hooks 为扁平事件数组，每项运行 `python3 "${CURSOR_PLUGIN_ROOT}/scripts/cursor_gate.py"`，`failClosed: true`（`beforeSubmitPrompt` 为 `false`、`timeout: 10`）、`timeout: 30`，不是 Claude 的嵌套 hooks 格式。

官方协议来源：
- https://cursor.com/docs/reference/plugins.md
- https://cursor.com/docs/hooks.md

## 任务与 CLI

`CURSOR_PLUGIN_ROOT` 是插件根，不是项目根。适配器使用 `CURSOR_PROJECT_DIR` 或 `workspace_roots`，Shell 的 `tool_input.working_directory` 保留实际执行目录，并从该目录查找最近的 `ai-workflow.yaml`，不折叠为工作区根；`CURSOR_PROJECT_DIR` 只是默认目录，合法子目录可覆盖，兄弟目录等真正冲突仍拒绝；不采用可能指向插件的 cwd。多根缺少明确选择、目录不一致或格式无效时 preToolUse 拒绝。只有明确找到 `ai-workflow.yaml`（或当前会话持有活跃规划登记）才启用门禁；未接入项目旁路允许，便于初始化。已接入项目的配置、任务或输入错误不降级为旁路。

`conversation_id` 原样映射引擎 `session_id`，`sessionStart` 同时通过 `env` 注入 `WORKFLOW_HOST=cursor` 与 `CURSOR_CONVERSATION_ID`（供 `check-hooks` 等前置诊断复用）并在 `additional_context` 输出完整 `Cursor conversation_id` 与 CLI 绝对路径。每轮会话唯一任务 lookup 沿用共享逻辑，歧义不猜测。读取基线仍由 CLI `begin` 或 `read-baseline` 输出完整正文并登记；Cursor Read 输出没有已验证的完整读取回执契约，不会自动登记。

在 Cursor 中每次运行引擎 CLI 前明确设置 `WORKFLOW_HOST=cursor`，不要假定所有场景下子进程环境变量都能透传到后续 Shell。使用插件脚本绝对路径和显式 `--root`，先查询 `--help`：

```bash
WORKFLOW_HOST=cursor python3 "/绝对路径/plugins/workflow-core/scripts/workflow_engine_cli.py" --root "/项目根" status --task "T1"
```

共享门禁只为固定引擎脚本允许这个精确环境前缀，不允许任意环境包装或 shell 拼接。引擎与看板状态默认保存在项目内 `.speclock/`（自动写 `.speclock/.gitignore`；首次无库时可自动从旧版 `$CODEX_HOME/workflow-engine` 只读备份迁移）；如用 `WORKFLOW_ENGINE_HOME` 或 `--db`，必须确保门禁、CLI 和看板读取同一库，不能只对某次 CLI 使用另一个库后期待自动关联。

Agent 先核对 `check-hooks` 或入口响应中的 `hooks.hook_active` 为 `true`，再用 `request-confirmation`（或 `prepare --request-tier`）登记当前任务版本和 `conversation_id`，随后展示档位。用户在聊天中单独回复 `选轻量档`、`选标准档` 或 `选完整档`（英文会话为 `Select Light Tier`、`Select Standard Tier` 或 `Select Full Tier`），由 `beforeSubmitPrompt` 登记。完整档方案就绪后，另登记 `--kind approval`（命令会自动在 `.speclock/reviews/` 生成只读 Markdown 审阅稿并内联返回 `review_markdown` 与 `presentation_note`，要求在聊天中完整展示全文），让用户回复 `批准方案`（英文会话为 `Approve Proposal`）。Agent 用 `status` 核实登记结果。`AskQuestion` 的普通工具结果继续只用于问答，因为 Cursor 尚未文档化可用于定档的选择回执。

## 支持边界

- preToolUse 显式输出 allow/deny，绝不输出 ask；Git 调查的 updated_input 保留原字段并禁用外部 diff/textconv。
- Read/Glob/Grep/rg/SemanticSearch/ListDir/GlobFileSearch 与 AskQuestion 允许只读调查；`PreToolUse` 仅守护本地仓库写入——原生编辑工具、写入本地仓库的 MCP 工具、本地修改/解释器执行型 Shell 命令、`.speclock/` 状态路径与 `Task` 委派须通过共享引擎就绪检查，外部非本地写入型 MCP/浏览器工具及非本地写入型 CLI（如 `apifox` 查询、`git` 只读管道）直接放行；`explore` 名称本身不构成只读证明。Write/Delete/Edit/StrReplace 只接受非空字符串目标 `file_path`、`path`、`target_file`；`EditNotebook` 兼容 `file_path`/`path`/`target_file`/`notebook_path`/`target_notebook`；未知 schema 拒绝；目标范围、会话和基线由共享门禁验证。
- `init` 规划态下放行固定 `vendor_check_docs.py --output scripts/check_docs.py`（拒绝 `--force` 与越界目标）以及原生 `Write`/`Edit`/`StrReplace`/`apply_patch` 写已登记配置与文档骨架；`prd-breakdown` 与 `clarify` 规划态下放行原生 `Write`/`Edit`/`StrReplace`/`apply_patch` 写已登记产品文档与直接模块卡，以及只读 `check_docs.py --root <项目根>`（`--check-config` 可选）；`--check` 只读校验独立放行。`AskQuestion` 可直接用于 `clarify` 需求澄清访谈，不进入确认授权链。
- Task 仅在父任务已绑定且当前轮次授权就绪时允许委派；子 Agent 不因此取得独立授权，必须使用其实际会话重新绑定、读取基线。subagentStart 仅返回合法的 permission/user_message，提醒不等于全部子工具路径已覆盖；Cursor 未回调的写入路径不在保证内。插件不是系统沙箱。
- sessionStart 返回 `env`（`WORKFLOW_HOST`、`CURSOR_CONVERSATION_ID`）与 `additional_context`；postToolUse 返回适用的 `additional_context`。
- 看板 CLI 使用 `WORKFLOW_HOST=cursor` 将服务运行信息存放在状态目录（默认项目内 `.speclock/dashboard.json`），任务数据来自同一状态目录下的引擎数据库。

## 验证口径

`test_cursor_gate.py` 使用官方输入形状模拟进程回调，并连接真实 Engine/CLI 验证绑定、`check-hooks`、`read-baseline`、start、规划态 `StrReplace`/`vendor_check_docs.py`、英文聊天定档审批和跨会话拒绝；还验证清单、格式故障拒绝、字符串工具结果、以及多个项目根。`python3 scripts/check.py` 覆盖根 Cursor marketplace JSON。上述是协议模拟与本机引擎集成，不是实际 Cursor E2E；真实安装、工具 schema、子 Agent 传播和用户终端交互仍需人工验收。
