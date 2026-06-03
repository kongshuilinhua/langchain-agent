"""
灵枢 Agent 平台 —— 模型调用三态熔断器。

🎯 架构角色：
    参考 Ragent (nageoffer/ragent) 的三态熔断器设计（CLOSED → OPEN → HALF_OPEN）。
    每个模型实例独立维护健康状态。当模型连续失败达到阈值时自动熔断，
    冷却期后进入半开状态放行探测请求，探测成功则恢复、失败则继续熔断。

    Ragent 的设计要点：
    - 每个模型独立熔断器实例（通过模型名作为 key）
    - CLOSED: 正常状态，记录连续失败次数
    - OPEN: 熔断状态，拒绝所有请求（快速失败，不发起实际 HTTP 调用）
    - HALF_OPEN: 冷却期后自动进入，放行 1 次探测请求
    - 探测成功 → CLOSED，探测失败 → OPEN（重新计时冷却期）

    与 Ragent 的三态对比：
    - Ragent 用 Resilience4j/自研 → Lingshu 用纯 Python threading
    - Ragent 通过 Spring Bean 管理 → Lingshu 集成到 OpenAICompatibleProvider
    - 两者都支持独立模型粒度的健康状态追踪
"""

import threading
import time
from enum import Enum


class CircuitState(Enum):
    CLOSED = "CLOSED"        # 正常——请求放行、记录失败
    OPEN = "OPEN"            # 熔断——拒绝请求、等待冷却
    HALF_OPEN = "HALF_OPEN"  # 半开——放行 1 次探测


class CircuitBreaker:
    """
    模型调用三态熔断器。

    🎯 状态转换：
        CLOSED ──(连续失败 >= threshold)──→ OPEN
        OPEN   ──(冷却 timewindow 秒后)──→ HALF_OPEN
        HALF_OPEN ──(探测成功)──→ CLOSED
        HALF_OPEN ──(探测失败)──→ OPEN

    🧠 默认参数：
        - failure_threshold=3: 连续失败 3 次触发熔断
        - timewindow=60: 冷却 60 秒后进入半开状态
    """

    def __init__(self, failure_threshold: int = 3, timewindow: int = 60):
        self.failure_threshold = failure_threshold
        self.timewindow = timewindow
        self._failures = 0
        self._last_failure_time = 0.0
        self._state = CircuitState.CLOSED
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """线程安全地读取当前状态（OPEN 状态在冷却期满后自动过渡到 HALF_OPEN）。"""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self.timewindow:
                    self._state = CircuitState.HALF_OPEN
                    self._failures = 0
            return self._state

    def allow_request(self) -> bool:
        """当前是否允许发起请求。CLOSED 或 HALF_OPEN 状态返回 True。"""
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self):
        """记录一次成功调用——重置为 CLOSED 状态。"""
        with self._lock:
            self._failures = 0
            self._state = CircuitState.CLOSED

    def record_failure(self):
        """记录一次失败调用——连续失败达到阈值时切换为 OPEN。"""
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.monotonic()
            if self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN

    def status(self) -> dict:
        """导出当前状态信息，供健康检查端点使用。"""
        with self._lock:
            return {
                "state": self._state.value,
                "failures": self._failures,
                "threshold": self.failure_threshold,
                "timewindow_s": self.timewindow,
            }
