"""认证核心模块单元测试，覆盖基础登录与令牌签发校验。"""
import unittest

from auth import TokenStore, login


class AuthTests(unittest.TestCase):
    """验证基础登录与 TokenStore 的核心行为。"""

    def test_login(self) -> None:
        """验证合法令牌返回 True，空串与空白串返回 False。"""
        self.assertTrue(login("ok"))
        self.assertFalse(login(""))
        self.assertFalse(login("   "))

    def test_issue_and_verify_token(self) -> None:
        """验证签发令牌可成功校验，未知或空令牌校验失败。"""
        store = TokenStore()
        token = store.issue_token("alice")
        self.assertTrue(token)
        self.assertTrue(store.verify_token(token))
        self.assertFalse(store.verify_token(token + "x"))
        self.assertFalse(store.verify_token("unknown-token"))
        self.assertFalse(store.verify_token(""))

    def test_issue_token_rejects_empty_subject(self) -> None:
        """验证签发令牌时传入空白主体会抛出 ValueError。"""
        store = TokenStore()
        with self.assertRaises(ValueError):
            store.issue_token("   ")
