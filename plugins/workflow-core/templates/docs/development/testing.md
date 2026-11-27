# Testing & Verification Standards

Maintain check commands, default verification platforms, and verification criteria here; individual test coverage notes live in test file headers, and task results/gaps live in task cards.

<!-- Note: commands must actually exist in the project and match ai-workflow.yaml; if they differ, this doc is authoritative and config should be synced. -->

Default Verification Platform: {{e.g. Android; iOS only when explicitly requested}}

```bash
{{docs check command}}
{{full check command}}
{{build command}}
```

| Tier | During Development | Before Delivery |
| --- | --- | --- |
| Docs Only | Verify related rules and links | {{docs check command}} |
| Light | Minimal repro or affected tests | {{targeted tests + static analysis}} |
| Standard | Related test baseline and targeted regression | {{full check command}} |
| Full | Risk-based baseline | {{full check + build + critical path acceptance}} |

- Code changes require formatting, static analysis, and relevant test results; state explicit reasons for anything not run instead of claiming pass.
- CI: {{CI config file and commands, or "none"}}
