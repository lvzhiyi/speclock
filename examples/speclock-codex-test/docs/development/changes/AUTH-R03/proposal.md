# AUTH-R03 API Token Expiration & Revocation

Per [Auth Module Task Cards](../../../product/tasks/auth-module.md), add optional TTL expiration and idempotent revocation to the in-memory `TokenStore`. The scope covers `src/auth.py`, `src/test_auth.py`, and this change directory. Persistence, cross-process revocation, login entrypoints, and other auth features are out of scope.

Existing `issue_token` calls may continue omitting `ttl_seconds`. New and updated methods must follow the [Technical Design](design.md), paying close attention to behavior at exact expiration vs. past expiration, and verification results for unexpired revoked tokens. All token comparisons must use `hmac.compare_digest`.

Run the auth unit tests and docs/config check per the task card acceptance criteria. To roll back, revert the changes made for this task across `TokenStore`, its tests, and these change docs.
