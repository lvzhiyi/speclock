# API Integration Standards

Maintain contract sources, integration environments, and test data conventions here; per-endpoint schemas and integration status belong in the API tool and corresponding technical tasks.

<!-- Note: generic contract verification, mocking, and integration checklists come from workflow-core:api-contract; keep only project-specific facts here. -->

## Contract Source

- API Tool: {{e.g. Apifox project "<name>", project ID in .apifox/settings.json}}
- Record contract changes in the linked proposal, design doc, or issue.

## Integration Boundaries

- Environment & Base URL Injection: {{e.g. --dart-define / .env}}; never put credentials in build flags.
- Response Envelope & Success Code: {{TBD}}
- Auth & Token Expiration Handling: {{TBD}}
- Restrict mocks to tests or explicit dev entrypoints; production paths must never return fake success data.

## Test Accounts & Data

- Share accounts and fixtures through secure team channels; document roles and reference locations here without credentials.
