# SpecLock

**English** | [简体中文](README.zh-CN.md) · [Demo video](https://github.com/user-attachments/assets/6c399680-073c-4bd3-8bb2-d61fae7f9972) · [v0.28.7](docs/development/release-0.28.7.md)

**Your coding agent says the tests passed. SpecLock requires the results before it accepts a review.**

SpecLock is a task workflow plugin for **Codex, Claude Code, and Cursor**. It checks that the agent reads your project standards before editing, runs the required checks on the current code, and leaves final acceptance to you.

## Quick start: run `AUTH-R03`

Try adding token expiry and revocation in an example project, without touching your own code.

> The new example is not yet on public `main`. If you already have a clean copy of `examples/speclock-codex-test` with `AUTH-R03` pending, you can use it now.

1. [Install `workflow-core` in Codex](#codex), then open the example as its own Git workspace. It is already configured; skip `init`.
2. Start a new Codex session, trust and enable the SpecLock hooks in `/hooks` or **Settings → Hooks**, then send:

   ```text
   $workflow-core:workflow Run AUTH-R03
   ```

3. Confirm the **Full** tier and approve the proposal after reviewing it. Once the required checks and review pass, the task card will say **评审通过，待人工验收** (review passed, awaiting human acceptance).

<details>
<summary>Set up a clean example workspace once it is available on main</summary>

Run in a shell with Git, `tar`, and Python 3.9+ available. Use a fresh folder: the example expects a `develop` review baseline.

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

## How it works

| Stage | You | Agent / SpecLock |
| --- | --- | --- |
| **Start** | Give a task ID or describe the goal and acceptance criteria. | Finds the task and asks about missing decisions. |
| **Approve** | Confirm the scope and tier. Review and approve the proposal separately for Full tasks. | Checks approvals and records that the required standards were read before implementation. |
| **Verify and review** | Step in only if a decision or prerequisite is missing. | Runs the required checks against the current code, then reviews against both the spec and project standards. Missing or stale verification blocks review. |
| **Accept** | Check the result and decide whether to accept it. | Hands over the evidence and any gaps. Review does not mark the task accepted. |

**Light** for small edits · **Standard** for scoped features and fixes · **Full** for higher-risk work, such as auth or breaking contracts. All tiers require human scope and tier confirmation, baseline reading, verification, and both review checks.

Send `$workflow-core:dashboard on` in Codex and open the returned local URL to see progress, verification results, and review evidence on the **read-only** dashboard.

## Installation

Use Python 3.9+ and Git. Start with `workflow-core`; extra plugins are optional.

### Codex

```bash
codex plugin marketplace add lvzhiyi/speclock --ref main
codex plugin add workflow-core@speclock
```

After installation or an update, trust and enable the plugin's hooks in `/hooks` or **Settings → Hooks** and start a new session. If confirmations are not recorded, check hook trust before retrying; see [tier selection and approval](plugins/workflow-core/skills/workflow/SKILL.md#在-agent-窗口定档).

### Claude Code

```bash
claude plugin marketplace add lvzhiyi/speclock
claude plugin install workflow-core@speclock
```

### Cursor

Add this repo as a marketplace and select `workflow-core`, or load `plugins/workflow-core` locally. See the [Cursor adapter guide](docs/development/cursor-adapter.md#安装与检查).

**Scope:** Hooks apply only to the tool paths the host actually routes through enabled callbacks. SpecLock is not a security sandbox. Integration tests do not replace a full test in a real client session.

## Use it in your project

1. Run `workflow-core:init` once per project (Codex: `$workflow-core:init`; Claude Code: `/workflow-core:init`). Review the proposed `ai-workflow.yaml`, required standards, and check commands.
2. Use `workflow-core:workflow` with a task ID or a short request. For a full PRD, use [`prd-breakdown`](plugins/workflow-core/skills/prd-breakdown/SKILL.md) first.
3. For an interrupted task, give the next session its task ID and [handoff notes](plugins/workflow-core/skills/handoff/SKILL.md), if available.

## More

- **Workflow reference:** [Workflow skill](plugins/workflow-core/skills/workflow/SKILL.md#任务路径) · [Handling failed checks](plugins/workflow-core/skills/verify/SKILL.md#失败处理顺序) · [Engine protocol and CLI](docs/development/workflow-engine.md#cli-示例)
- **Project tools:** [Read-only dashboard](plugins/workflow-core/skills/dashboard/SKILL.md) · [Local metrics](plugins/workflow-core/skills/metrics/SKILL.md) · [Standalone doc checker](plugins/workflow-core/scripts/vendor_check_docs.py)
- **Optional plugins:** [`stack-flutter`](plugins/stack-flutter), [`design-pixso`](plugins/design-pixso), and [`api-apifox`](plugins/api-apifox). Claude Code can install the [combined preset](README.zh-CN.md#可选插件). You can also use SpecLock alongside [Superpowers](https://github.com/obra/superpowers).
- **Project links:** [Issues](https://github.com/lvzhiyi/speclock/issues) · [Release notes](docs/development/release-0.28.7.md) · [MIT License](LICENSE)
