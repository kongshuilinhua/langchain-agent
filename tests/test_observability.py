"""可观测性单元测试：指标 record_* 不抛异常、/metrics 渲染、request-id contextvar 与日志 filter。

不依赖 prometheus_client 是否安装：未装时 record_* 为 no-op、render 返回提示文本。
"""

import logging

from core.observability import metrics
from core.observability.request_context import (
    RequestIdFilter,
    get_request_id,
    new_request_id,
    set_request_id,
)


def test_metrics_record_and_render_never_throw():
    metrics.record_http("GET", "/api/health", 200, 0.012)
    metrics.record_cache("embedding", True)
    metrics.record_cache("rag_result", False)
    metrics.record_rate_limit_rejection("register")
    metrics.record_circuit_open("model:x")
    body, content_type = metrics.render()
    assert isinstance(body, bytes) and content_type
    if metrics.enabled():  # 装了 prometheus_client 才有真实指标输出
        assert b"lingshu_http_requests_total" in body


def test_request_id_contextvar_roundtrip():
    request_id = new_request_id()
    assert len(request_id) == 16
    set_request_id(request_id)
    assert get_request_id() == request_id


def test_request_id_filter_injects_field():
    set_request_id("trace-abc")
    record = logging.LogRecord("n", logging.INFO, "p", 1, "msg", None, None)
    assert RequestIdFilter().filter(record) is True
    assert record.request_id == "trace-abc"
