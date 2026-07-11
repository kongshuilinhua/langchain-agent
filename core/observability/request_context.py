"""请求级 trace id（标准库 contextvars 实现，无额外依赖）。

中间件在每个请求入口生成/透传 X-Request-ID，绑定到 contextvar；日志 filter 注入到每条日志，
实现「一个请求 → 一条 trace id → 贯穿所有日志与响应头」的全链路关联。
"""

from __future__ import annotations

import contextvars
import logging
import uuid

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id or "-")


def get_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """给每条日志记录注入 request_id 字段，供 formatter 使用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def install_request_id_logging() -> None:
    """
    给 root 与 uvicorn 日志的现有 handler 注入 request_id：附上 filter、并把 request_id 前缀进 formatter。

    🛡️ 防御式：在 handler 已存在（uvicorn 已配置）后调用；任何异常静默跳过，绝不因日志增强拖垮启动。
    """
    targets = [logging.getLogger(), logging.getLogger("uvicorn"), logging.getLogger("uvicorn.access")]
    for log in targets:
        for handler in list(getattr(log, "handlers", []) or []):
            try:
                handler.addFilter(RequestIdFilter())
                existing = handler.formatter._fmt if handler.formatter else "%(levelname)s:%(name)s:%(message)s"
                if "levelprefix" in existing:
                    continue
                if "request_id" not in existing:
                    handler.setFormatter(logging.Formatter("[%(request_id)s] " + existing))
            except Exception:  # pragma: no cover - 日志增强失败不致命
                continue
