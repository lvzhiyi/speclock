<!-- Note: lean 3-in-1 engineering baseline template for small/medium projects (<=200 lines) wanting a single required baseline doc. Remove this comment after generating. -->
# Engineering Standards (Core Baseline)

> Maintain durable coding, architecture, and verification baselines here; do not put page/route lists, single-task logs, or debugging transcripts here.

## 1. Architecture & Layer Boundaries

- Directory Responsibilities: {{fill in layer responsibilities and dependency directions from top-level directories; TBD}}
- Do not cross layer boundaries; put shared capabilities in shared layers instead of duplicating logic.
- Never store secrets (credentials, tokens, production keys) in the repo, logs, or hardcoded client code.

## 2. Code Style & Generated Artifacts

- Formatting & Static Analysis: {{e.g. dart format / ruff / eslint and config file path}}
- Naming & Comments: {{project naming and doc-comment conventions; "follow language idioms" if none}}
- Generated Code: {{generation command and output directory; never hand-edit generated files}}

## 3. Verification Commands & Platforms

- Docs Check: `{{python3 scripts/check_docs.py --root .}}`
- Light Check: `{{targeted tests + static analysis command}}`
- Standard Check: `{{full test suite + static analysis command}}`
- Full Check: `{{standard check + default platform build command}}`
- Default Verification Platform: {{e.g. android / linux / web}}; other platforms run only when explicitly requested.
- Only commands that actually ran and exited 0 count as passed; mocks/unit tests do not replace real integration or device E2E runs.
