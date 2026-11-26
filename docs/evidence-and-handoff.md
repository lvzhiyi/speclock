# 可核对凭证与人机交接

模型越强，「防它出错」越不值钱，「证明它没出错」越值钱。SpecLock 把每次 AI 交付变成可核对的记录，并划清人与 Agent 的权责。

## 可核对凭证

| 凭证要素 | SpecLock 的实现 |
| --- | --- |
| **结构化留存** | 以「任务 → `rounds[]` 轮次 → `attempts[]` 阶段尝试 → `evidence[]` 证据」保存在 SQLite（默认 `.speclock/state.sqlite`），事件 `history` 保留原时点快照（见[引擎权威层级](development/workflow-engine.md#权威与兼容)）。 |
| **结果由引擎实测** | `run` 按 `ai-workflow.yaml` 的 `verify` 精确匹配命令列表并实际执行，留存命令、`exit_code` 与截断输出；协议中没有 `mark-pass` 命令（见[CLI 示例](development/workflow-engine.md#cli-示例)）。 |
| **绑定当前代码** | 对工作区 Git 纳管文件与未忽略文件做 SHA-256 快照；执行前后内容一致才记为 `passed`，代码改动后证据自动投影为 `stale`。 |
| **绑定当前检查配置** | 任务记录 `verify_config_digest`；`ai-workflow.yaml` 检查清单变化会使已有验证与评审失效，须更新计划并重跑（见[档位配置强制验证](development/workflow-engine.md#档位配置强制验证)）。 |
| **批准绑定方案内容** | 完整档 `approve_proposal` 绑定当前轮次的 `control_digest`；通过 `update_task` 修改目标、范围、验收、方案等控制字段会自动撤销批准并重置待办（见[小接口](development/workflow-engine.md#小接口)）。 |
| **规范读取回执** | `read-baseline` / `register_baseline` 记录路径、`sha256`、`bytes_read` 与 `complete: true`；超限截断不登记，文档变更后不能复用旧回执。 |
| **评审问题闭环** | 双轴评审报告绑定 `round_id`、`control_digest` 与验证 `snapshot`；必修项不能在重试报告中删除逃逸，必须在同一评审轴、用同一编号显式标记 `resolved: true` 才关闭。 |
| **只读核对与导出** | 提供只读 `status`、`snapshot`、`history` 查询，以及 `render-md` 导出当前方案与状态审阅稿，不修改任务状态。 |

## 人机交接协议

### 人与 Agent

- **决策边界**：定档（`confirm-tier`）、批准完整档方案（`approve-proposal`）和人工退回（`return-task`）只能由人确认。
- **终态边界**：Agent 最高只到 `review_passed`。绑定的任务卡自动回写「评审通过，待人工验收」，完成框 `[x]` 留给人勾；`check_docs.py` 会拦截完成框与非终态协作状态并存的情况。
- **统一口径**：[deliver](../plugins/workflow-core/skills/deliver/SKILL.md) 明确区分「实施完成，待验证」「验证通过，待评审」「评审未通过」与「评审通过」，不再用「自测完成」冒充交付终态。

### Agent 与 Agent（跨会话 / 换执行者）

- **执行者绑定**：`bind_executor` 绑定轮次的 `executor`、`session_id` 与 `binding_version`；切换执行者或会话会递增 `binding_version`，既有人工确认和方案批准继续有效，但规范必须重新完整读取，TDD 决策和验证/评审成功记录不可借用。
- **可恢复交接**：[handoff](../plugins/workflow-core/skills/handoff/SKILL.md) 要求未完成且需跨会话的任务把交接快照写入仓库，恢复时以引擎 `status` / `snapshot` / `history` 和当前 Git 工作区为准，不依赖上一会话的聊天记忆；`resume` 只登记活动，不跳过任何门禁。

### 团队协作

- **过程可见**：[Dashboard](../plugins/workflow-core/skills/dashboard/SKILL.md) 只读展示当前档位、待办进度、阻塞项、验证结果与双轴评审证据，无需翻聊天记录追进度。
- **结案对账**：`reconcile-cards` 在任务卡先于本机进入结案状态时自动关闭未开工的本地任务；已开工任务则报告冲突，交由人决定退回、拆分或放弃。

## 当前边界

- **证据默认不出本机**：状态目录 `.speclock/` 默认被忽略且不提交进 Git；团队评审时，第三方需要在 CI 中对 PR 重跑同一套 `verify` 检查作为独立复核。
- **流程约束而非防篡改签名**：同一系统用户可以修改本地数据库、检查程序和运行环境，人工确认记录 `human_process=true` 只表示流程属性，不构成密码学签名或安全沙箱。
- **快照尚未绑定 Git commit**：工作区快照是基于文件内容的 SHA-256，目前没有直接绑定具体 commit 或 PR head。
- **退出码 0 不等于测试质量**：引擎只能证明配置命令实际运行且退出码为 0，测试本身是否充分仍依赖项目检查设计。
- **门禁覆盖边界**：钩子只拦截宿主实际经过已启用回调的工具路径，具体限制见 [引擎协议](development/workflow-engine.md#当前限制与后续适配)。

## 相关文档

- [任务级工作流引擎协议 v2](development/workflow-engine.md)
- [中断与恢复交接技能](../plugins/workflow-core/skills/handoff/SKILL.md)
- [Agent 总结与人工交接技能](../plugins/workflow-core/skills/deliver/SKILL.md)
- [只读看板技能](../plugins/workflow-core/skills/dashboard/SKILL.md)
- [SpecLock 中文说明](../README.zh-CN.md)
