"""
灵枢 Agent 平台 —— API 频率限制模块。

🎯 架构角色：
    - slowapi（内存计数器）：保留作进程内兜底；多 worker 下各算各的，仅作粗粒度全局默认。
    - `redis_rate_limit`：基于 Redis ZSET 滑动窗口的分布式限流依赖，进程间共享计数，
      多 worker / 多实例下额度一致；Redis 不可用时 fail-open 放行（软依赖）。

    建议配额：
    - 全局默认：200 请求/分钟
    - 聊天流式端点：30 请求/分钟（高消耗）
    - 注册端点：10 请求/分钟（防滥用）
"""

from collections.abc import Callable

from fastapi import HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    headers_enabled=True,  # 在响应头中返回 X-RateLimit-* 信息
)


def redis_rate_limit(limit: int, window_seconds: int, *, scope: str) -> Callable[[Request], None]:
    """
    生成一个基于 Redis 滑动窗口的 FastAPI 限流依赖。

    🎯 用法：`dependencies=[Depends(redis_rate_limit(10, 60, scope="register"))]`
        或作为参数 `_: None = Depends(redis_rate_limit(...))`。

    🛡️ 按「scope + 客户端 IP」隔离计数；超限抛 429 并带 Retry-After。
        Redis 不可用时 rate_limit_check 返回放行，不阻断请求。
    """

    def dependency(request: Request) -> None:
        from core.services.rag_cache import redis_store

        client_id = get_remote_address(request) or "anonymous"
        allowed, _remaining = redis_store.rate_limit_check(f"rl:{scope}:{client_id}", limit, window_seconds)
        if not allowed:
            from core.observability.metrics import record_rate_limit_rejection

            record_rate_limit_rejection(scope)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"message": "请求过于频繁，请稍后再试。", "error_code": "rate_limited"},
                headers={"Retry-After": str(window_seconds)},
            )

    return dependency
