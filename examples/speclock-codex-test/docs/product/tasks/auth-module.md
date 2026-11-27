# Auth Module Task Cards

> Maintained following the `workflow-core` 7-field lean task card convention; see [Engineering & Coding Standards](../../development/standards.md) for business and coding rules.

### AUTH-R01 Basic Login Token Non-Empty Validation

- [x] Subtask completed (human acceptance passed)
- Source: Auth service initial baseline
- Status: Accepted
- Acceptance: Empty strings and whitespace-only tokens return False; non-empty tokens return True.

### AUTH-R02 Token Issuance & Constant-Time Verification

- [x] Subtask completed (human acceptance passed)
- Source: Auth service security hardening
- Status: Accepted
- Acceptance: Support issuing tokens via TokenStore and verifying them with hmac.compare_digest; invalid or unknown tokens return False.

### AUTH-R03 API Token Expiration & Revocation

- [ ] Subtask completed (check only after human acceptance)
- Source: Auth service security governance
- Status: Pending
- Acceptance: 1) TokenStore.issue_token accepts an optional ttl_seconds parameter (must be > 0 when provided, otherwise raise ValueError); 2) verify_token returns False once expired, and accepts an optional now parameter for deterministic testing; 3) add revoke_token(token) to revoke a token so verify_token returns False even before expiration, remaining idempotent for unknown or already-revoked tokens; 4) compare all tokens with hmac.compare_digest and add unit tests covering valid, expired, revoked, and invalid TTL edge cases.

### AUTH-R04 Token Rotation & Per-Subject Active Session Limit

- [ ] Subtask completed (check only after human acceptance)
- Source: Auth service security governance v2 (pending clarification demo for `workflow-core:clarify`)
- Status: Blocked; Pending Clarification
- Scope & Non-Goals: Extend `TokenStore` to support rotating an active token into a replacement token and limiting the number of active tokens per `subject`; persistence across processes and external storage remain out of scope (exact rotation, eviction, and error boundaries pending clarification below).
- Acceptance: Pending finalization via `workflow-core:clarify` — must cover valid rotation, expired/revoked/unknown token handling, per-subject active limit enforcement, constant-time token comparison, deterministic `now` time testing, and unit tests.
- Pending (Q01): When rotating a token via `rotate_token`, should the old token be invalidated immediately or kept valid for a configurable grace period for in-flight concurrent requests? If a grace period is supported, can the old token be rotated again or explicitly revoked during that window? | Impact: `TokenStore` state model, concurrent in-flight request behavior, and rotation acceptance scenarios | Resume when: Old-token invalidation policy and grace-period boundaries are confirmed
- Pending (Q02): How should the replacement token's expiration be computed (inherit remaining TTL, reset using the original `ttl_seconds`, or accept an explicit new `ttl_seconds` override), and how should non-expiring tokens be handled? | Impact: `rotate_token` signature, expiration calculation, and TTL boundary test cases | Resume when: Replacement token TTL inheritance and override rules are confirmed
- Pending (Q03): When a per-subject active token limit (`max_active_per_subject`) is configured and reached, should issuing a new token evict the oldest/soonest-expiring token or reject the request with an exception? Should expired tokens be lazily pruned before counting against the limit? | Impact: `TokenStore.__init__` / `issue_token` contract and overflow behavior | Resume when: Limit-overflow policy and expired-token pruning rules are confirmed
- Pending (Q04): When `rotate_token` is called with an invalid, expired, or revoked token, should it return `None` or raise an exception (e.g., `ValueError`), and should rotation check the per-subject limit before or after invalidating the old token? | Impact: Error-handling contract, interaction with Q01/Q03 boundaries, and failure acceptance cases | Resume when: Error return style and rotation counting order are confirmed
