"""可观测性子系统：Prometheus 指标 + 请求级 trace id。

均为软依赖 / 防御式设计：prometheus_client 未安装时指标全部降级为 no-op，
不影响主流程；request id 用标准库 contextvars 实现，无额外依赖。
"""
