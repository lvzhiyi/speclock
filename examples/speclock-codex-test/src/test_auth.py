"""Unit tests for the core auth module covering basic login and token issuance/verification."""
import hmac
import unittest
from unittest.mock import patch

from auth import TokenStore, login


class AuthTests(unittest.TestCase):
    """Verify core behavior of login and TokenStore."""

    def test_login(self) -> None:
        """Valid tokens return True; empty and whitespace-only strings return False."""
        self.assertTrue(login("ok"))
        self.assertFalse(login(""))
        self.assertFalse(login("   "))

    def test_issue_and_verify_token(self) -> None:
        """Issued tokens verify successfully; unknown or empty tokens fail verification."""
        store = TokenStore()
        token = store.issue_token("alice")
        self.assertTrue(token)
        self.assertTrue(store.verify_token(token))
        self.assertFalse(store.verify_token(token + "x"))
        self.assertFalse(store.verify_token("unknown-token"))
        self.assertFalse(store.verify_token(""))

    def test_issue_token_rejects_empty_subject(self) -> None:
        """Issuing a token for a whitespace-only subject raises ValueError."""
        store = TokenStore()
        with self.assertRaises(ValueError):
            store.issue_token("   ")

    def test_token_expires_after_deadline(self) -> None:
        """A token stays valid through the exact expiration timestamp."""
        store = TokenStore()
        token = store.issue_token("alice", ttl_seconds=2.5, now=100.0)
        self.assertTrue(store.verify_token(token, now=101.0))
        self.assertTrue(store.verify_token(token, now=102.5))
        self.assertFalse(store.verify_token(token, now=102.6))

    def test_default_clock_controls_expiration(self) -> None:
        """Issuance and verification use wall time when now is omitted."""
        store = TokenStore()
        with patch("auth.time.time", return_value=100.0):
            token = store.issue_token("alice", ttl_seconds=10)
        with patch("auth.time.time", return_value=111.0):
            self.assertFalse(store.verify_token(token))

    def test_issue_token_rejects_invalid_ttl(self) -> None:
        """A supplied TTL must be a finite positive number."""
        store = TokenStore()
        for ttl in (0, -1, float("inf"), float("-inf"), float("nan"), "5", True):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                store.issue_token("alice", ttl_seconds=ttl, now=100.0)

    def test_revocation_is_immediate_and_idempotent(self) -> None:
        """Revocation invalidates an unexpired token and preserves other tokens."""
        store = TokenStore()
        token = store.issue_token("alice", ttl_seconds=10, now=100.0)
        other = store.issue_token("bob")
        store.revoke_token(token)
        store.revoke_token(token)
        store.revoke_token("unknown")
        self.assertFalse(store.verify_token(token, now=101.0))
        self.assertTrue(store.verify_token(other, now=1000.0))

    def test_token_operations_compare_every_record(self) -> None:
        """A match in the first record still requires comparing later records."""
        store = TokenStore()
        token = store.issue_token("alice")
        store.issue_token("bob")
        with patch("auth.hmac.compare_digest", wraps=hmac.compare_digest) as compare:
            self.assertTrue(store.verify_token(token))
            self.assertEqual(compare.call_count, 2)
            compare.reset_mock()
            store.revoke_token(token)
            self.assertEqual(compare.call_count, 2)
