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
