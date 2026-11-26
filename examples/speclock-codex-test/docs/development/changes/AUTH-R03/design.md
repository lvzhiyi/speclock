# AUTH-R03 Technical Design

- `issue_token(subject, ttl_seconds=None, *, now=None)` accepts a finite positive number as TTL. Invalid TTL values raise `ValueError`. Token records retain the subject and token string, and store an optional absolute expiration timestamp. Tokens issued without TTL do not expire.
- `verify_token(token, now=None)` validates against the provided timestamp or `time.time()` by default. Unrevoked tokens remain valid when `now == expires_at`, and expire only when `now > expires_at`. Unknown or revoked tokens return `False`.
- `revoke_token(token)` removes matching records. Repeated calls for unknown or already-revoked tokens remain idempotent. Both verification and revocation scan all records using `hmac.compare_digest`.
- Tests use fixed deterministic timestamps to cover valid tokens, exact expiration boundary, post-expiration failure, revocation, invalid TTLs, and full-scan constant-time comparison.
