# {{Project Name}}

<!-- Note: navigation and collaboration conventions only; do not put business rules, node details, or task state here. Keep only links to generated docs. -->

{{One-line summary of what the project does and who it serves}}

## Documentation Map

| Category | Document | Scope |
| --- | --- | --- |
| Requirements | [PRD](requirements/prd.md) | Product goals, scope, business rules, open questions |
| Tasks | [Task Overview](tasks/overview.md) | Module grouping, priorities, module card links |
| Design | [Design Index](design/index.md) | Design files, screen/node mapping, authoritative source, design diffs |
| Engineering | [Coding](../development/coding.md), [Architecture](../development/architecture.md), [Testing](../development/testing.md) | Coding conventions, layering, check commands, verification criteria |
| Engineering | [UI Standards](../development/ui.md), [API Integration](../development/api-integration.md) | UI rules, API contracts, test accounts/data |

## Collaboration Conventions

- Development workflow entrypoint: SpecLock `workflow-core:workflow` skill. Project config lives in `ai-workflow.yaml` at repo root; domain terms live in the [Glossary](glossary.md).
- Business rules belong in the PRD, product status in module cards, design nodes in the design index, and execution steps/progress in the workflow engine.
