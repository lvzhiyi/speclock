"""Unit tests for the core auth module covering basic login and token issuance/verification."""
import unittest

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
