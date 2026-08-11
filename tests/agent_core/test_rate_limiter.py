"""AIRAGAgent.infrastructure.rate_limiter 测试。

用 FakeRedis（conftest 注入）验证：
- 滑动窗口计数：窗口内放行、超限拒绝
- remaining 计数递减
- reset 清理
- Redis 不可用时放行（容灾）
- RateLimiterFactory 单例 + 配置驱动

注意：rate_limiter 用 `zadd(key, {str(now): now})` 记录请求，
同一秒内的多次请求共享同一 ZSET member（str(now) 相同），只算 1 次。
测试需 mock time.time 让每次调用返回不同值，才能验证计数逻辑。
"""
import pytest

from AIRAGAgent.infrastructure.rate_limiter import (
    RateLimiter, RateLimiterFactory, get_chat_rate_limiter, get_tool_rate_limiter,
)
from tests.agent_core.conftest import _fake_redis


@pytest.fixture(autouse=True)
def incrementing_time(monkeypatch):
    """让 time.time() 每次调用递增 1，确保每次 is_allowed 产生独立 ZSET member。"""
    import time as _time
    _t = [_time.time()]
    def _fake_time():
        _t[0] += 1
        return _t[0]
    from AIRAGAgent.infrastructure import rate_limiter as _rl
    monkeypatch.setattr(_rl.time, "time", _fake_time)


# ═══════════════════════════════════════════════
# 滑动窗口计数
# ═══════════════════════════════════════════════

def test_within_limit_allowed():
    limiter = RateLimiter(key_prefix="test", max_requests=3, window_seconds=60)
    for i in range(3):
        allowed, remaining = limiter.is_allowed("user_1")
        assert allowed is True
        assert remaining == 2 - i  # 2, 1, 0


def test_over_limit_rejected():
    limiter = RateLimiter(key_prefix="test", max_requests=2, window_seconds=60)
    limiter.is_allowed("user_2")  # 1
    limiter.is_allowed("user_2")  # 2
    allowed, remaining = limiter.is_allowed("user_2")  # 3rd
    assert allowed is False
    assert remaining == 0


def test_different_identifiers_independent():
    limiter = RateLimiter(key_prefix="test", max_requests=2, window_seconds=60)
    # user_a 用 2 次
    limiter.is_allowed("user_a")
    limiter.is_allowed("user_a")
    # user_b 仍可用
    allowed, _ = limiter.is_allowed("user_b")
    assert allowed is True
    # user_a 已超限
    allowed, _ = limiter.is_allowed("user_a")
    assert allowed is False


def test_different_prefixes_independent():
    """不同 key_prefix 的限流器互不影响"""
    limiter1 = RateLimiter(key_prefix="chat", max_requests=1, window_seconds=60)
    limiter2 = RateLimiter(key_prefix="tool", max_requests=1, window_seconds=60)
    limiter1.is_allowed("user_x")
    # chat 限流命中
    allowed_chat, _ = limiter1.is_allowed("user_x")
    assert allowed_chat is False
    # tool 仍可用
    allowed_tool, _ = limiter2.is_allowed("user_x")
    assert allowed_tool is True


# ═══════════════════════════════════════════════
# remaining 递减
# ═══════════════════════════════════════════════

def test_remaining_decrements():
    limiter = RateLimiter(key_prefix="dec", max_requests=5, window_seconds=60)
    _, r0 = limiter.is_allowed("u")
    assert r0 == 4
    _, r1 = limiter.is_allowed("u")
    assert r1 == 3
    _, r2 = limiter.is_allowed("u")
    assert r2 == 2


def test_remaining_zero_at_limit():
    limiter = RateLimiter(key_prefix="z", max_requests=3, window_seconds=60)
    limiter.is_allowed("u")
    limiter.is_allowed("u")
    _, remaining = limiter.is_allowed("u")  # 3rd, last allowed
    assert remaining == 0


# ═══════════════════════════════════════════════
# reset
# ═══════════════════════════════════════════════

def test_reset_clears_counter():
    limiter = RateLimiter(key_prefix="rst", max_requests=2, window_seconds=60)
    limiter.is_allowed("u")
    limiter.is_allowed("u")
    # 已超限
    assert limiter.is_allowed("u")[0] is False
    # reset 后恢复
    limiter.reset("u")
    allowed, _ = limiter.is_allowed("u")
    assert allowed is True


def test_reset_nonexistent_identifier_no_error():
    limiter = RateLimiter(key_prefix="rst2", max_requests=2, window_seconds=60)
    # reset 不存在的 identifier 不应报错
    limiter.reset("never_existed")


# ═══════════════════════════════════════════════
# Redis 不可用（容灾放行）
# ═══════════════════════════════════════════════

def test_redis_unavailable_allows_all(monkeypatch):
    """Redis 不可用时应放行所有请求（容灾）"""
    from AIRAGAgent.infrastructure import rate_limiter as rl_mod
    monkeypatch.setattr(rl_mod, "is_redis_available", lambda: False)
    limiter = RateLimiter(key_prefix="down", max_requests=1, window_seconds=60)
    for _ in range(10):
        allowed, remaining = limiter.is_allowed("u")
        assert allowed is True
        assert remaining == 1  # max_requests


def test_redis_exception_fallback(monkeypatch):
    """Redis 调用异常时应放行（容灾）"""
    limiter = RateLimiter(key_prefix="err", max_requests=1, window_seconds=60)

    def _boom():
        raise ConnectionError("redis down")
    # 必须打补丁 rate_limiter 模块内已导入的 get_redis_client 引用，
    # 而非 redis_client 模块（import 时已绑定）
    from AIRAGAgent.infrastructure import rate_limiter as _rl
    monkeypatch.setattr(_rl, "get_redis_client", _boom)

    allowed, remaining = limiter.is_allowed("u")
    assert allowed is True
    assert remaining == 1  # max_requests（容灾值）


def test_reset_redis_unavailable_no_error(monkeypatch):
    from AIRAGAgent.infrastructure import rate_limiter as rl_mod
    monkeypatch.setattr(rl_mod, "is_redis_available", lambda: False)
    limiter = RateLimiter(key_prefix="rst3", max_requests=1, window_seconds=60)
    limiter.reset("u")  # 不应抛异常


# ═══════════════════════════════════════════════
# Factory 单例 + 配置驱动
# ═══════════════════════════════════════════════

def test_factory_returns_singleton():
    """同一 name 返回同一实例"""
    a = RateLimiterFactory.get("chat")
    b = RateLimiterFactory.get("chat")
    assert a is b


def test_factory_different_names_different_instances():
    a = RateLimiterFactory.get("chat")
    b = RateLimiterFactory.get("tool")
    assert a is not b


def test_factory_reads_config():
    """从 redis_conf.rate_limit 读取配置"""
    # conftest 设置 chat: max=3, window=60
    limiter = RateLimiterFactory.get("chat")
    assert limiter.max_requests == 3
    assert limiter.window_seconds == 60


def test_factory_default_config():
    """未配置的 name 走默认值"""
    limiter = RateLimiterFactory.get("unconfigured")
    assert limiter.max_requests == 30  # 默认
    assert limiter.window_seconds == 60


def test_get_chat_rate_limiter():
    limiter = get_chat_rate_limiter()
    assert limiter.key_prefix == "chat"
    assert limiter.max_requests == 3


def test_get_tool_rate_limiter():
    limiter = get_tool_rate_limiter()
    assert limiter.key_prefix == "tool"
    assert limiter.max_requests == 30


# ═══════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════

def rl_mod_redis():
    import AIRAGAgent.infrastructure.redis_client as rc
    return rc
