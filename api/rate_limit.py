"""
灵枢 Agent 平台 —— API 频率限制模块。

🎯 架构角色：
    Phase 2 引入 slowapi 作为短期限流方案（内存计数器模式）。
    Phase 3 将升级为基于 Redis ZSET + 信号量 + Pub/Sub 的分布式方案（参考 Ragent）。

    当前配置：
    - 全局默认：200 请求/分钟
    - 聊天流式端点：30 请求/分钟（高消耗）
    - 注册端点：10 请求/分钟（防滥用）
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    headers_enabled=True,  # 在响应头中返回 X-RateLimit-* 信息
)
