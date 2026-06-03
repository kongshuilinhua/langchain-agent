"""
灵枢 Agent 平台 —— 线程安全的 SSE 事件发送器。

🎯 架构角色：
    参考 Ragent (nageoffer/ragent) SseEmitterSender.java 的设计思想，
    用 Python threading.Lock + _closed 标记实现等效的 CAS (Compare-And-Swap) 关闭语义。

    Ragent 原始设计要点（从 Java 源码分析）：
    - AtomicBoolean closed: 所有对连接状态的读写通过原子变量
    - sendEvent 中 closed.get() 快速路径检查，已关闭则静默丢弃
    - complete/closeWithError 用 CAS 确保"只关闭一次"
    - 发送异常被吸收而非向上传播（避免破坏 HTTP 流式响应协议）
    - completeWithError 通过 SSE 通知客户端异常终止

    Python 等效方案：
    - threading.Lock 替代 AtomicBoolean
    - _closed 标记替代 CAS 操作
    - send() 返回 None 表示已关闭/发送失败，调用方据此停止 yield
"""

import threading
from typing import Any, Callable


class SseSender:
    """
    线程安全的 SSE 事件发送器。

    🎯 使用方式：
        sender = SseSender(sse_event_formatter)
        for event in runner.run_events(...):
            payload = sender.send(event["event"], event.get("data", {}))
            if payload is None:
                break       # 连接已关闭或发送失败
            yield payload
        sender.close()       # 正常关闭

    🛡️ 防御性设计：
        - send() 在 _closed 状态下静默返回 None，不会抛异常破坏流式响应
        - close() / close_with_error() 幂等——多次调用只有第一次生效
        - 线程安全——在并发 yield/异常场景下不会出现竞态条件
    """

    def __init__(self, event_formatter: Callable[[str, dict], str]):
        self._lock = threading.Lock()
        self._closed = False
        self._format = event_formatter

    def send(self, event: str, data: dict) -> str | None:
        """
        发送一个 SSE 事件。已关闭时静默返回 None。

        参考 Ragent: sendEvent() 中 if (closed.get()) return;
        """
        with self._lock:
            if self._closed:
                return None
        try:
            return self._format(event, data)
        except Exception:
            self.close_with_error()
            return None

    def close(self):
        """
        正常关闭发送器，幂等。

        参考 Ragent: complete() 中 closed.compareAndSet(false, true)
        """
        with self._lock:
            self._closed = True

    def close_with_error(self):
        """
        异常关闭发送器，幂等。

        参考 Ragent: closeWithError() → emitter.completeWithError(throwable)
        Python 侧等效：标记关闭状态，让上层感知到连接不可用。
        """
        with self._lock:
            self._closed = True

    @property
    def is_closed(self) -> bool:
        """外部检查发送器是否已关闭。"""
        with self._lock:
            return self._closed
