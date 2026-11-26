"""Core authentication service providing basic login token checks and token store management."""
from __future__ import annotations

import hmac
import secrets


def login(token: str) -> bool:
    """Validate that a basic login token is a non-empty, non-whitespace string."""
    return isinstance(token, str) and bool(token.strip())


class TokenStore:
    """In-memory token store for secure issuance and constant-time verification of access tokens."""

    def __init__(self) -> None:
        """Initialize an empty token store."""
        self._tokens: list[tuple[str, str]] = []

    def issue_token(self, subject: str) -> str:
        """Issue a random access token for the given subject; raises ValueError if subject is blank."""
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("subject must not be empty")
        token = secrets.token_urlsafe(24)
        self._tokens.append((subject.strip(), token))
        return token

    def verify_token(self, token: str) -> bool:
        """Verify whether a token is valid using constant-time comparison."""
        if not isinstance(token, str) or not token:
            return False
        matched = False
        for _, stored in self._tokens:
            if hmac.compare_digest(stored, token):
                matched = True
        return matched
