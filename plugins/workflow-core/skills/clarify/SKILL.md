---
name: clarify
description: grill-me 式深度需求澄清。面对协作状态为「待确认」、含未决待确认项、目标/范围/验收模糊、或需求/设计/代码存在冲突的任务卡或需求时使用；先自查事实，再沿决策树逐枝追问、给出推荐答案并收敛共识，将确认结论回写任务卡与产品文档。
---

# 需求深度澄清（grill-me）

下文的 `${CLAUDE_PLUGIN_ROOT}` 指当前技能所在的插件根目录。如果它没有被替换成绝对路径（如在 Codex 中），从已加载的 `SKILL.md` 路径向上三级定位，执行命令时直接代入绝对路径。

对需求待确认或存在关键歧义的任务卡，采用 `grill-me` 式结构化访谈：先在仓库与既有来源中查清事实，再把仍需人工拍板的分歧整理成决策树逐枝追问，收敛共识后将结论回写到任务卡与产品文档。

## 何时使用

- 模块任务卡的 `协作状态` 为「待确认」（或英文 `Blocked` / `Pending Confirmation`），或包含未决 `- 待确认：` / `依赖与待确认` 项。
- 需求说明 `## 待确认问题` 中存在与当前任务卡相关的未决 `Qxx`。
- 用户主动调用 `clarify` 澄清卡片或需求，或 `workflow` / `kickoff` / `prd-breakdown` 核对时发现目标、范围/非目标、状态流转、角色权限、数值/时间/异常边界、接口契约、UI 交互或验收标准仍存在会改变实施或验收的歧义与冲突。

## 会话级规划登记（回写文档前必做）

仅在用户确认澄清结论、准备回写规划文档时执行 `workflow_planning_cli.py open --operation clarify` 登记精确文件清单（不为需求澄清创建假实施任务）；只放行配置文档角色（`requirements` / `glossary` / `design_index` / `overview` / `home`）及 `docs.cards_dir` 下的直接模块卡；仅通过原生编辑工具（`Write` / `Edit` / `MultiEdit` / `StrReplace` / `apply_patch`）写入，收尾、取消或交接前务必 `close`：

```bash
WORKFLOW_HOST=HOST python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_planning_cli.py" open --root "项目绝对根" --session "${SESSION}" --operation clarify --path "精确目标.md" --ttl 1800
WORKFLOW_HOST=HOST python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_planning_cli.py" close --root "项目绝对根" --session "${SESSION}"
```

`HOST` 取 `cursor` / `codex` / `claude`，`${SESSION}` 取宿主真实会话 ID（取不到即报告缺项、不编造）：
- **Cursor**：`${CURSOR_PLUGIN_ROOT}` 仅在插件配置中展开，Shell 命令须用绝对路径并前缀 `WORKFLOW_HOST=cursor`，`${SESSION}` 取 `sessionStart` 注入的 `conversation_id` / `CURSOR_CONVERSATION_ID`。
- **Claude Code**：`${SESSION}` 取 `SessionStart` 注入的 `session_id` / `CLAUDE_SESSION_ID`（`SessionStart` 已持久化 `WORKFLOW_HOST=claude`，显式传入亦可）。
- **Codex**：`${SESSION}` 取 `CODEX_THREAD_ID`，前缀 `WORKFLOW_HOST=codex`。

`ai-workflow.yaml`、入口文件、开发规范骨架与产品代码均不属于 `--operation clarify` 授权范围。

## 1. 先查事实，不问已知

提问前先做只读调查（只读文件、Git 状态和外部设计/契约查询，不写仓库）：

1. 读取 `ai-workflow.yaml`、目标模块任务卡、需求说明（含 `## 待确认问题` 与已确认决定）、术语表（`docs.glossary`）及设计索引（`docs.design_index`）。
2. 检查相关源码、测试、工程规范与进行中变更，以及已关联的外部设计稿（如 Pixso）或接口契约（如 Apifox）。
3. 区分「既定事实」（代码或权威文档已明确给出的约束与现状）与「待人决策的问题树（Decision Tree）」，梳理问题间的前置依赖关系。
4. **严禁把代码或现有文档已明确给出的信息拿来反问用户。**

## 2. 沿决策树逐枝追问

按当前卡片实际涉及范围裁剪以下排查维度，只追问会改变实施或验收的分歧点：

- **业务目标与非目标边界**：首期做什么、明确不做什么、与既有行为的兼容/替换关系。
- **状态流转与生命周期**：前置条件、终态、幂等性、并发/重复操作、取消与回滚规则。
- **角色、权限与数据隔离**：访问边界，未登录、越权、失效态下的实际表现。
- **数值/时间/配额边界与空态/异常/降级**：超限、上游失败、空数据、部分失败、跨端一致性。
- **设计与契约差异**：PRD 与设计稿冲突、同名多稿主稿未定、设计稿缺失状态、接口字段或错误码未定。
- **术语一致性**：出现术语表缺失、含糊或一词多义的业务词时，先提议建议定义，待用户确认后再入表。
- **可验证的验收场景**：成功、空态、业务拒绝、边界、异常、恢复与适用平台。

访谈纪律：

1. **逐枝推进、按依赖排序**：先问决定范围与核心语义的上游根决策，收到明确答复后再沿选定分支展开下游细节；每轮聚焦 **1 个决策点**（或同一分支内紧密相关的 1～2 个小问题），**禁止一次性抛出长列表轰炸用户**。
2. **每题给出推荐答案与依据**：每个问题写清：① 具体问题（保留原有 `Q01`/`Q02` 等编号）；② 影响范围（影响哪些实现、契约、UI 或验收）；③ 候选方案与**推荐答案及理由/取舍**，让用户能快速确认或调整。
3. **追问到底，拒绝隐性假设**：遇到「差不多」「按常规做」等模糊答复时，把默认方案拆成可证伪的边界与验收条款请用户明确确认；**超时、沉默或「继续」均不能代替具体结论**。
4. **外部阻塞不强逼拍板**：若某问题确实依赖当前用户之外的角色（如后端接口契约、外部设计主稿、其他负责人），如实保留为待确认阻塞项（写清影响、负责人或「待指定」、恢复条件），不强迫猜测，继续澄清其他不受影响的分支。

宿主提问工具与授权隔离：

- 优先使用当前宿主可用的原生提问工具（Claude Code `AskUserQuestion`、Codex `request_user_input` 或 `request_user_input_async`，Cursor `AskQuestion`）；使用 Codex `request_user_input_async` 时须按 `workflow` 调用 `clock.sleep` 保持回合等待点击，勿立即结束回合；工具不可用或需要自由补充时直接在聊天中提问。
- **严禁在需求澄清问题中携带 `workflow-confirm:` 标记**；普通澄清绝不进入档位确认或方案审批授权链。

## 3. 收敛共识复核

所有可决分支收口后，向用户展示结构化的「澄清结论摘要」供确认：

- 明确后的目标、范围与非目标
- 逐条决策结论与依据（保留原 `Qxx` 编号）
- 补齐后的验收场景
- 仍保留的外部阻塞项及恢复条件（如有）
- 拟变更的模块卡 `协作状态`（阻塞全清 → `待处理`；仍有外部阻塞 → 保持 `待确认`）

## 4. 回写文档与状态同步

收到用户对结论摘要的确认后，按当前任务情况落盘：

- **路径 A（无实施任务或建任务前）**：执行 `workflow_planning_cli.py open --operation clarify` 登记本次需改动的精确文件清单，仅用原生编辑工具回写：
  - **模块卡**：补全/更新 `范围与非目标`、`验收`、`依赖与待确认`（已解决项记录结论或移除未决阻塞；未决外部阻塞保持 `- 待确认：<具体缺项或冲突>｜影响：<阻塞的子需求/步骤>｜恢复条件：<取得什么后继续>` 或英文 `- Pending (Q01): <open question or conflict> | Impact: <blocked scope/step> | Resume when: <condition to proceed>` 格式）；全部阻塞解决时，跟随任务卡语言将状态更新为 `待处理`（英文卡片写 `Pending`，**严禁勾选完成框 `[x]`**）。
  - **需求说明**（如涉及业务规则或 `Qxx`）：把结论写回对应业务章节，并在 `## 待确认问题` 保留原编号、问题、结论、确认人/来源、时间与依据，不只删除待确认项。
  - **术语表 / 设计索引**：仅当本次澄清确认了新术语或设计主稿/映射时同步更新。
  - 运行只读文档检查并确认 0 错误（项目配置另有 `verify.docs` 时一并运行），随后立即执行 `workflow_planning_cli.py close`：
    ```bash
    python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_docs.py" --root .
    ```
- **路径 B（已存在引擎任务）**：用 `update-task` 保留原问题编号把已解决的 `dependencies` 项更新为 `done`（保留其余依赖），并同步受影响的 `goal` / `scope` / `acceptance` / `proposal`；若任务尚未进入 `implementing` 且需同步模块卡或产品文档，按路径 A 完成规划登记回写并 `close`；若控制摘要变化导致既有批准或基线回执失效，按 `workflow` / `tiering` 补齐。

授权边界与下一步：

- 若用户仅要求澄清卡片：回写、校验并 `close` 后结束本轮，报告卡片新状态与剩余阻塞（如有），提示后续可用 `workflow` 开始定档执行，**不自行转入产品实施**。
- 若已通过 `workflow` / `kickoff` 授权执行该任务：全部阻塞澄清完毕后在**同一会话**无缝进入 `kickoff` / `tiering` 推进，无需用户再发一次「执行」；仍有外部阻塞时只暂停受影响部分并说明恢复条件。

## 5. 交付检查

- [ ] 提问前已自查仓库文档、源码、设计与契约，未向用户反问已有事实
- [ ] 所有可决分支已收敛为明确结论与可验证验收场景，未擅自拍板业务规则，未在澄清问题中使用 `workflow-confirm:`
- [ ] 无法由当前用户拍板的外部阻塞已原位保留 `- 待确认：…｜影响：…｜恢复条件：…` 或 `- Pending (Q01): ... | Impact: ... | Resume when: ...`
- [ ] 模块卡、需求说明（及涉及的术语表/设计索引）已按文档职责回写，未误勾完成框 `[x]`
- [ ] 已运行 `check_docs.py --root .`（及项目 `verify.docs`）确认 0 错误，并已执行 `workflow_planning_cli.py close`
