"""Prometheus 指标（软依赖）。

🛡️ prometheus_client 未安装时 `_ENABLED=False`，所有 record_* 变成 no-op，
   /metrics 返回纯文本提示——不引入硬依赖、不破坏主流程。

🎯 自定义指标刻意串起前几个 Phase 的工作，让它们「看得见」：
   - 缓存命中率（Phase 3 embedding / rag 结果缓存）
   - 限流拒绝数（Phase 3 分布式限流）
   - 熔断打开次数（Phase 3 熔断器）
   - HTTP QPS / 延迟直方图（平台级）
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:  # pragma: no cover - 取决于是否安装 prometheus_client
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

    _ENABLED = True
except Exception:  # pragma: no cover
    _ENABLED = False

if _ENABLED:
    _HTTP_REQUESTS = Counter(
        "lingshu_http_requests_total", "HTTP 请求计数", ["method", "path", "status"]
    )
    _HTTP_LATENCY = Histogram(
        "lingshu_http_request_duration_seconds", "HTTP 请求延迟（秒）", ["method", "path"]
    )
    _CACHE_EVENTS = Counter(
        "lingshu_cache_events_total", "缓存命中/未命中", ["cache", "result"]
    )
    _RATE_LIMIT_REJECTIONS = Counter(
        "lingshu_rate_limit_rejections_total", "限流拒绝（429）计数", ["scope"]
    )
    _CIRCUIT_OPENS = Counter(
        "lingshu_circuit_breaker_opens_total", "熔断器打开次数", ["name"]
    )


def enabled() -> bool:
    return _ENABLED


def record_http(method: str, path: str, status: int, duration_seconds: float) -> None:
    if not _ENABLED:
        return
    _HTTP_REQUESTS.labels(method, path, str(status)).inc()
    _HTTP_LATENCY.labels(method, path).observe(duration_seconds)


def record_cache(cache: str, hit: bool) -> None:
    """cache: 'embedding' / 'rag_result'；hit=True 命中。"""
    if not _ENABLED:
        return
    _CACHE_EVENTS.labels(cache, "hit" if hit else "miss").inc()


def record_rate_limit_rejection(scope: str) -> None:
    if not _ENABLED:
        return
    _RATE_LIMIT_REJECTIONS.labels(scope).inc()


def record_circuit_open(name: str) -> None:
    if not _ENABLED:
        return
    _CIRCUIT_OPENS.labels(name).inc()


def render() -> tuple[bytes, str]:
    """返回 (body, content_type)，供 /metrics 端点输出。"""
    if not _ENABLED:
        return (b"# prometheus_client is not installed; metrics are disabled.\n", "text/plain; charset=utf-8")
    return (generate_latest(), CONTENT_TYPE_LATEST)
