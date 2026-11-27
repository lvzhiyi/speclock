# Documentation Skeleton Templates

`init` copies these templates into the project on demand (default `docs/`), creating only missing files without overwriting existing ones. Chinese templates live under `templates/zh/`.

- `{{...}}` are placeholders: replace with detected facts when generating; write `TBD` for unknowns and never leave curly braces.
- Remove links pointing to ungenerated documents to avoid broken links.
- Remove `<!-- Note: ... -->` AI instructions after generating.

| Template | When Generated |
| --- | --- |
| `product/index.md`, `product/requirements/prd.md`, `product/tasks/overview.md` | init |
| `development/standards.md` (lean 3-in-1 baseline, recommended for small/medium projects) | init (lean mode, replaces coding/architecture/testing below) |
| `development/coding.md`, `architecture.md`, `testing.md` | init (split mode, for large projects) |
| `product/design/index.md` | init, when a design tool is used |
| `product/glossary.md` | init (skeleton only, do not invent terms) |
| `development/ui.md` | init, when the project has UI |
| `development/api-integration.md` | init, when the project integrates backend APIs |
| Module card (`templates/task-card.md`) | prd-breakdown when first splitting a module |
| Handoff note (`templates/handoff.md`) | handoff on first cross-session handoff |
