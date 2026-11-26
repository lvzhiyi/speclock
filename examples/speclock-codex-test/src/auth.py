"""认证服务核心模块，提供基础令牌校验与令牌存储管理。"""
from __future__ import annotations

import hmac
import secrets


def login(token: str) -> bool:
    """校验基础登录令牌是否为非空有效字符串。"""
    return isinstance(token, str) and bool(token.strip())


class TokenStore:
    """内存令牌存储，负责安全签发与恒定时间校验访问令牌。"""

    def __init__(self) -> None:
        """初始化空令牌存储容器。"""
        self._tokens: list[tuple[str, str]] = []

    def issue_token(self, subject: str) -> str:
        """为指定主体签发随机访问令牌，主体为空白时抛出 ValueError。"""
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("主体标识不能为空")
        token = secrets.token_urlsafe(24)
        self._tokens.append((subject.strip(), token))
        return token

    def verify_token(self, token: str) -> bool:
        """使用恒定时间比对校验令牌是否有效。"""
        if not isinstance(token, str) or not token:
            return False
        matched = False
        for _, stored in self._tokens:
            if hmac.compare_digest(stored, token):
                matched = True
        return matched
