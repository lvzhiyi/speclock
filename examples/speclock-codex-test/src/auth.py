"""Core authentication service providing basic login token checks and token store management."""
from __future__ import annotations

import hmac
import math
import secrets
import time
from threading import Lock


def login(token: str) -> bool:
    """Validate that a basic login token is a non-empty, non-whitespace string."""
    return isinstance(token, str) and bool(token.strip())


class TokenStore:
    """In-memory token store for secure issuance and constant-time verification of access tokens."""

    def __init__(self) -> None:
        """Initialize an empty token store."""
        self._tokens: list[tuple[str, str, float | None]] = []
        self._lock = Lock()

    def issue_token(
        self, subject: str, ttl_seconds: float | None = None, *, now: float | None = None
    ) -> str:
        """Issue a token for a nonblank subject with an optional positive, finite TTL.

        Calculate expiration from now or the system clock. Invalid subjects
        and TTLs raise ValueError. Omitting the TTL gives the token no deadline.
        """
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("subject must not be empty")

        expires_at = None
        if ttl_seconds is not None:
            if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
                raise ValueError("ttl_seconds must be a finite positive number")
            try:
                ttl = float(ttl_seconds)
            except OverflowError as error:
                raise ValueError("ttl_seconds must be a finite positive number") from error
            if ttl <= 0 or not math.isfinite(ttl):
                raise ValueError("ttl_seconds must be a finite positive number")
            expires_at = (time.time() if now is None else now) + ttl

        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tokens.append((subject.strip(), token, expires_at))
        return token

    def verify_token(self, token: str, now: float | None = None) -> bool:
        """Check that token is active at now, which defaults to the system clock.

        A token is active through its expiration timestamp. Unknown and revoked
        tokens return False.
        """
        if not isinstance(token, str) or not token.isascii() or not token.strip():
            return False
        with self._lock:
            checked_at = time.time() if now is None else now
            matched = False
            # Keep scanning after a match so the scan length does not reveal its position.
            for _, stored, expires_at in self._tokens:
                if hmac.compare_digest(stored, token) and (
                    expires_at is None or checked_at <= expires_at
                ):
                    matched = True
            return matched

    def revoke_token(self, token: str) -> None:
        """Remove all matching records. Unknown or already revoked tokens have no effect."""
        if not isinstance(token, str) or not token.isascii() or not token.strip():
            return
        with self._lock:
            # Scan the complete store before replacing it, including when a match is found.
            self._tokens = [
                record for record in self._tokens if not hmac.compare_digest(record[1], token)
            ]
