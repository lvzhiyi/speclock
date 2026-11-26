# Engineering & Coding Standards

This repository provides the core authentication service. All code and documentation changes must strictly follow these baseline standards across implementation, verification, and review.

## 1. Constant-Time Security Comparisons
- All comparisons of tokens, secrets, and sensitive credentials must use the standard library `hmac.compare_digest`.
- Direct string equality (`==`) on token values is forbidden to prevent timing side-channel attacks.
- Invalid inputs (such as empty strings, whitespace-only strings, wrong types, or non-positive numeric arguments) must be explicitly rejected or raise the documented exception.

## 2. Deterministic Time Testability
- Public methods involving token issuance timestamps, TTL calculation, or expiration checks must accept an optional `now: Optional[float] = None` parameter.
- When `now` is `None`, default to `time.time()`; when a TTL is set, evaluate expiration against the explicit timestamp threshold.
- Unit tests must pass deterministic timestamps to cover exact boundary and post-expiration cases, and must not rely on real `time.sleep`.

## 3. English Comments & Docstrings
- All public classes, methods, and functions must have clear English docstrings explaining their core responsibility, key parameters, and boundary behavior.
- Non-obvious security checks or state transition logic must include concise English comments explaining the rationale.

## 4. Required Verification & Gate Discipline
- Implement both business logic and tests using only the Python standard library; do not introduce third-party dependencies.
- After any code or documentation change, both verification commands below must pass completely:
  - Unit tests: `python3 -m unittest discover -s src`
  - Docs & config check: `python3 scripts/check_docs.py --check-config`
- Never weaken assertions, skip test cases, or suppress checks to fake a passing verification.
- When a task card passes final review, only update the collaboration status field; never check the human acceptance checkbox on behalf of a human.
