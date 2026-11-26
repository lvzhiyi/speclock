# AUTH-R03 技术设计

- `issue_token(subject, ttl_seconds=None, *, now=None)` 可接受有限正数作为 TTL。非法 TTL 抛出 `ValueError`。令牌记录保留主体和令牌，并保存可选的绝对过期时间。省略 TTL 时签发的令牌没有过期时间。
- `verify_token(token, now=None)` 使用传入时间或默认的 `time.time()` 校验。未吊销令牌在 `now == expires_at` 时仍有效，仅在 `now > expires_at` 时因过期失效。未知或已吊销令牌返回 `False`。
- `revoke_token(token)` 删除匹配记录。对未知或已经吊销的令牌重复调用保持幂等。校验和吊销均用 `hmac.compare_digest` 扫描所有记录。
- 测试使用固定时间戳，覆盖正常校验、过期临界点、超过期限、吊销、非法 TTL 和全量比对。
