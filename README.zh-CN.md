# SpecLock

[English](README.md) | **简体中文** · [演示视频](https://github.com/user-attachments/assets/6c399680-073c-4bd3-8bb2-d61fae7f9972) · [v0.28.7](docs/development/release-0.28.7.md)

**AI 说「测试过了」还不够。SpecLock 要看到验证结果，才允许评审。**

SpecLock 是面向 **Codex、Claude Code 和 Cursor** 的任务工作流插件。它让 Agent 改代码前先读项目规范，评审前对当前代码跑完规定检查，最后把验收权留给你。

## 快速上手：执行 `AUTH-R03`

在示例项目里为 API Token 加上过期和吊销校验，不动你自己的项目。

> 新示例尚未同步到公开 `main`。如果你已有 `examples/speclock-codex-test` 的干净副本，且 `AUTH-R03` 为「待处理」，可以先在本地试用。

1. [给 Codex 安装 `workflow-core`](#codex)，把示例作为独立 Git 项目打开。示例已有配置，不用运行 `init`。
2. 新开 Codex 会话，在 `/hooks` 或 **Settings → Hooks** 信任并启用 SpecLock 钩子，然后在聊天里发送：

   ```text
	 $workflow-core:dashboard on
   $workflow-core:workflow 开始执行任务 AUTH-R03
   ```

3. 按提示选**完整档**，看过方案后再批准。规定检查和评审通过后，任务卡会变成 **「评审通过，待人工验收」**，不会自动勾完成。

<details>
<summary>示例同步到 main 后，如何准备一份干净副本</summary>

需要 Git、`tar` 和 Python 3.9+。在全新目录里跑，下面会创建示例评审所用的 `develop` 基线。

```bash
git clone https://github.com/lvzhiyi/speclock.git &&
  demo=$(mktemp -d "${TMPDIR:-/tmp}/speclock-demo.XXXXXX") &&
  git -C speclock archive HEAD:examples/speclock-codex-test > "$demo/example.tar" &&
  tar -xf "$demo/example.tar" -C "$demo" &&
  rm "$demo/example.tar" &&
  git -C "$demo" init -b develop &&
  git -C "$demo" add . &&
  git -C "$demo" -c user.name='SpecLock Demo' -c user.email=demo@example.invalid commit -m 'Example baseline' &&
  printf 'Open in Codex: %s\n' "$demo"
```

</details>

## 工作流一览

| 阶段 | 你做什么 | Agent / SpecLock 做什么 |
| --- | --- | --- |
| **发任务** | 给任务号，或说清目标和验收条件。 | 找任务，有关键缺项就问。 |
| **确认后开工** | 确认范围与档位；完整档另审方案。 | 核对授权，读完必读规范后开始实施。 |
| **验证与评审** | 只有缺决定或执行条件时才需要介入。 | 对当前代码真跑规定检查，再按需求和工程规范两边评审。没跑完或证据过期，不能进评审。 |
| **人工验收** | 检查结果，决定是否验收。 | 交接证据和未覆盖项，不替你勾完成。 |

**轻量**：局部小改动 · **标准**：范围明确的功能和修复 · **完整**：认证、破坏性契约变更等高风险任务。三档都要人工确认范围和档位、读规范、跑验证、做双轴评审。

在 Codex 中发送 `$workflow-core:dashboard on`，打开返回的本机链接，就能在**只读看板**查看任务进度、验证结果和评审证据。

## 安装

需要 Python 3.9+ 和 Git。先装 `workflow-core`，其他插件按需添加。

### Codex

```bash
codex plugin marketplace add lvzhiyi/speclock --ref main
codex plugin add workflow-core@speclock
```

安装或升级后，到 `/hooks` 或 **Settings → Hooks** 信任并启用插件钩子，再新开会话。若定档或批准没有记录，先检查钩子是否受信任，不必反复发送确认口令。详见[定档与方案批准](plugins/workflow-core/skills/workflow/SKILL.md#在-agent-窗口定档)。

### Claude Code

```bash
claude plugin marketplace add lvzhiyi/speclock
claude plugin install workflow-core@speclock
```

### Cursor

从本仓库添加 marketplace 并选择 `workflow-core`，或本地加载 `plugins/workflow-core`。详见 [Cursor 适配说明](docs/development/cursor-adapter.md#安装与检查)。

**门禁边界：**只覆盖宿主实际调用了已启用钩子的工具路径，不是安全沙箱。引擎集成测试不等于真实客户端端到端验收。

## 在自己的项目中使用

1. 每个项目先跑一次 `workflow-core:init`（Codex：`$workflow-core:init`；Claude Code：`/workflow-core:init`），核对生成的配置、必读规范和检查命令。
2. 用 `workflow-core:workflow` 给出任务号或描述需求。有完整 PRD，再先用 [`prd-breakdown`](plugins/workflow-core/skills/prd-breakdown/SKILL.md) 拆成任务卡。
3. 换会话时发任务号，有[交接记录](plugins/workflow-core/skills/handoff/SKILL.md)就一并给出。

## 可选插件

- **Flutter / Pixso / Apifox**：按需添加 [`stack-flutter`](plugins/stack-flutter)、[`design-pixso`](plugins/design-pixso)、[`api-apifox`](plugins/api-apifox)。Apifox 需单独[安装 CLI 并登录](https://apifox.com/apifox-cli-installation-guide.md)；Pixso 首次使用时按提示授权。
- **Claude Code 组合包**：先运行 `claude plugin marketplace add flutter/agent-plugins`，再运行 `claude plugin install preset-flutter-pixso-apifox@speclock`。
- **Superpowers**：可以搭配使用。Superpowers 提供开发方法，SpecLock 负责项目里的授权、验证证据与评审门禁。

## 深入了解

- **流程与恢复：**[工作流技能](plugins/workflow-core/skills/workflow/SKILL.md#任务路径) · [验证失败怎么处理](plugins/workflow-core/skills/verify/SKILL.md#失败处理顺序) · [引擎协议与 CLI](docs/development/workflow-engine.md#cli-示例)
- **项目工具：**[看板](plugins/workflow-core/skills/dashboard/SKILL.md) · [流程度量](plugins/workflow-core/skills/metrics/SKILL.md) · [独立文档检查脚本](plugins/workflow-core/scripts/vendor_check_docs.py)
- **参与项目：**[Issues](https://github.com/lvzhiyi/speclock/issues) · [版本说明](docs/development/release-0.28.7.md) · [MIT 许可证](LICENSE)
