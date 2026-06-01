from __future__ import annotations

import json
from dataclasses import dataclass

from core.config import get_settings


@dataclass
class CacheLookup:
    """
    统一的缓存检索回执数据结构。
    """
    hit: bool
    value: dict | None = None
    backend: str = "none"


class OptionalRedisStore:
    """
    非阻塞式可选 Redis 缓存存储器。

    🎯 意图与工程大局观：
        在大并发大流量 Agent 交互场景中，Redis 作为全平台 RAG 知识片段缓存和异步文件解析任务进度（Job）的核心缓存介质。
        
    🛡️ 平滑降级与高可用设计：
        - 采取**“非强依赖设计（Soft Dependency）”**：若未配置 Redis 或 Redis 在服务运行期发生网络中断/故障瘫痪，
          系统会自动且静默地将缓存读写短路，降级为“缓存未命中（Cache Miss）”状态，转而由数据库或实时模型提供计算。
        - 坚决杜绝因 Redis 单点崩溃而导致前端 Web / API 聊天接口全面报 500 的重大事故。
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self._error = ""
        if not self.settings.redis_url:
            return
        try:
            import redis

            # 🧠 魔鬼数字：socket_timeout=1 秒，避免 Redis 连接阻塞主线程过长时间
            self._client = redis.Redis.from_url(self.settings.redis_url, decode_responses=True, socket_timeout=1)
            # 🛡️ 前置心跳探测：强制 ping 一次以验证连接确实通畅，若物理链路不通立刻抛错触发降级
            self._client.ping()
        except Exception as exc:
            self._client = None
            self._error = str(exc)[:240]

    @property
    def available(self) -> bool:
        """Redis 连接是否处于激活可用就绪状态。"""
        return self._client is not None

    def status(self) -> dict:
        """暴露给系统健康检查元数据的状态监测板。"""
        configured = bool(self.settings.redis_url)
        return {
            "configured": configured,
            "available": self.available,
            "backend": "redis" if self.available else "none",
            "required": bool(configured and self.settings.rag_cache_enabled),
            "error": self._error or None,
        }

    def get_json(self, key: str) -> CacheLookup:
        """
        根据 Key 安全获取反序列化的缓存 JSON 对象。

        🛡️ 防御性设计：
            - 所有 Redis 读请求包入 Try-Catch 逻辑中，当缓存服务在运行期发生宕机，返回未击中而不破坏业务主进程。
            - 针对损坏的缓存数据（非标准 JSON）自动捕获 JSONDecodeError 规避系统异常。
        """
        if not self._client:
            return CacheLookup(hit=False)
        try:
            raw = self._client.get(key)
        except Exception:
            return CacheLookup(hit=False)
        if not raw:
            return CacheLookup(hit=False, backend="redis")
        try:
            return CacheLookup(hit=True, value=json.loads(raw), backend="redis")
        except json.JSONDecodeError:
            return CacheLookup(hit=False, backend="redis")

    def set_json(self, key: str, value: dict, ttl_seconds: int) -> None:
        """
        安全写入 JSON 键值并设置 TTL 超时生命周期。

        🧠 魔鬼数字与参数防线：
            - `max(int(ttl_seconds), 1)`: 确保生存秒数永不为 0 或负数，防止被外部错误入参触发 Redis 内部协议级参数校验异常。
            - `ensure_ascii=False`: 保持原始中文字符串写入，减小压缩包体体积，极大优化网络传输吞吐性能。
        """
        if not self._client:
            return
        try:
            self._client.setex(key, max(int(ttl_seconds), 1), json.dumps(value, ensure_ascii=False))
        except Exception:
            return

    def set_job(self, job_id: str, value: dict, ttl_seconds: int = 86400) -> None:
        """
        写入异步知识库分块解析任务（Job）进度状态。
        默认 TTL 为 86400 秒（24小时），超时自动清理释放 Redis 内存。
        """
        self.set_json(f"knowledge_job:{job_id}", value, ttl_seconds)

    def get_job(self, job_id: str) -> CacheLookup:
        """
        读取异步知识库分块解析任务（Job）进度状态。
        """
        return self.get_json(f"knowledge_job:{job_id}")


# 全局单例缓存工具实例，全局统一维护同一个 Redis 连接池
redis_store = OptionalRedisStore()
