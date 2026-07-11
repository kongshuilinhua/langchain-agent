from __future__ import annotations

import functools
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass

from core.config import get_settings

logger = logging.getLogger(__name__)


def ttl_with_jitter(ttl_seconds: int, ratio: float = 0.1) -> int:
    """
    给 TTL 叠加 ±ratio 的随机抖动，返回秒数（>=1）。

    🛡️ 防缓存雪崩：版本化 key 在文档更新后会让一批缓存同时失效，若 TTL 又完全一致，
        会出现「同一秒大量 key 集体过期 → 瞬时全部回源」的尖峰。抖动把过期时刻摊开。
    """
    base = max(int(ttl_seconds), 1)
    delta = int(base * ratio)
    if delta <= 0:
        return base
    return max(1, base + random.randint(-delta, delta))

# 🛡️ redis 为软依赖：未安装时退化为「永远缓存未命中」。
# 把 RedisError 单独抽出，作为降级闸门「只吞连接类异常、放过代码缺陷」的判定依据：
#   - 已安装 → 真实的 redis.exceptions.RedisError 类；
#   - 未安装 → 空元组 `()`，`except ()` 不匹配任何异常（且此时 _client 恒为 None，根本进不到 try）。
try:  # pragma: no cover - 取决于运行环境是否装了 redis
    from redis.exceptions import RedisError as _RedisError

    _REDIS_ERRORS: tuple = (_RedisError,)
except Exception:  # pragma: no cover
    _REDIS_ERRORS = ()


def _redis_guard(default):
    """
    Redis 操作的统一降级闸门（装饰器）。

    🛡️ 设计意图（修正历史教训）：
        - 未配置 / 未连接 → 直接返回 `default`，不触发任何网络调用。
        - 运行期连接类异常（RedisError）→ 记日志、标记运行时失败、返回 `default` 平滑降级。
        - **其它异常（AttributeError 等代码缺陷）照常向上抛出，绝不静默吞掉**——
          过去满屏的 `except Exception: pass` 正是把 `redis_store.client` 这类 AttributeError
          一并吃掉，导致令牌撤销整条链路坏掉却毫无报错。本闸门只放行真正的连接故障。
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            if not self._client:
                return default
            try:
                result = func(self, *args, **kwargs)
            except _REDIS_ERRORS as exc:
                self._mark_runtime_failure(exc)
                return default
            else:
                # 一次成功调用即自愈，清掉上一轮的运行期错误标记
                if self._runtime_error:
                    self._runtime_error = ""
                return result

        return wrapper

    return decorator


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
        self._error = ""           # 启动期连接/握手错误（一次性）
        self._runtime_error = ""   # 运行期最近一次调用失败（可自愈，供健康检查暴露）
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
        """
        Redis 客户端是否就绪。

        🧠 注意：这里只表示「客户端对象存在且启动期握手通过」，**不因单次运行期失败而翻转**——
            否则一次网络抖动就会让缓存永久关闭、且永不重连。运行期健康状况由 status() 的
            `degraded` 字段单独暴露，既能让监控看见问题，又保留下一次调用自动重试/自愈的机会。
        """
        return self._client is not None

    def _mark_runtime_failure(self, exc: Exception) -> None:
        """记录运行期 Redis 调用失败，并通过日志暴露，便于排障与健康检查。"""
        self._runtime_error = str(exc)[:240]
        logger.warning("Redis runtime operation failed; degrading to cache-miss: %s", self._runtime_error)

    def status(self) -> dict:
        """暴露给系统健康检查元数据的状态监测板。"""
        configured = bool(self.settings.redis_url)
        return {
            "configured": configured,
            "available": self.available,
            "backend": "redis" if self.available else "none",
            "required": bool(configured and self.settings.rag_cache_enabled),
            # degraded：客户端存在但最近一次调用失败（运行期 Redis 抖动/宕机），监控据此告警
            "degraded": bool(self._runtime_error),
            "error": self._error or self._runtime_error or None,
        }

    @_redis_guard(CacheLookup(hit=False))
    def get_json(self, key: str) -> CacheLookup:
        """
        根据 Key 安全获取反序列化的缓存 JSON 对象。

        🛡️ 防御性设计：
            - Redis 连接故障由 `_redis_guard` 统一降级为「未命中」，不破坏业务主进程。
            - 针对损坏的缓存数据（非标准 JSON）就地捕获 JSONDecodeError 规避系统异常。
        """
        raw = self._client.get(key)
        if not raw:
            return CacheLookup(hit=False, backend="redis")
        try:
            return CacheLookup(hit=True, value=json.loads(raw), backend="redis")
        except json.JSONDecodeError:
            return CacheLookup(hit=False, backend="redis")

    @_redis_guard(None)
    def set_json(self, key: str, value: dict, ttl_seconds: int) -> None:
        """
        安全写入 JSON 键值并设置 TTL 超时生命周期。

        🧠 魔鬼数字与参数防线：
            - `max(int(ttl_seconds), 1)`: 确保生存秒数永不为 0 或负数，防止被外部错误入参触发 Redis 内部协议级参数校验异常。
            - `ensure_ascii=False`: 保持原始中文字符串写入，减小压缩包体体积，极大优化网络传输吞吐性能。
        """
        self._client.setex(key, max(int(ttl_seconds), 1), json.dumps(value, ensure_ascii=False))

    @_redis_guard(False)
    def exists(self, key: str) -> bool:
        """
        判断某个 Key 是否存在。

        🛡️ Redis 未配置 / 不可用 / 运行期出错时一律返回 False（视为不存在）。
            调用方（如令牌撤销黑名单）据此实现「降级放行」：查不到撤销记录即视为有效。
        """
        return bool(self._client.exists(key))

    @_redis_guard(False)
    def set_string(self, key: str, ttl_seconds: int, value: str) -> bool:
        """
        写入一个带 TTL 的纯字符串键值（区别于 set_json 的对象序列化）。

        🎯 用于令牌撤销黑名单等「只需标记存在性 + 自动过期」的轻量场景。
        返回 True 表示确实写入成功；Redis 不可用或运行期出错时返回 False（调用方据此判断是否降级）。
        """
        self._client.setex(key, max(int(ttl_seconds), 1), value)
        return True

    # ── Embedding 缓存 ──────────────────────────────────────────

    @staticmethod
    def _embedding_key(model: str, text: str) -> str:
        """按 (model, 文本) 生成稳定缓存键；\\x00 分隔避免 model/text 边界歧义。"""
        digest = hashlib.sha256(f"{model}\x00{text}".encode("utf-8")).hexdigest()
        return f"emb:{digest}"

    @_redis_guard(None)
    def get_embedding(self, model: str, text: str) -> list[float] | None:
        """读取缓存的向量；未命中 / Redis 不可用 / 数据损坏一律返回 None。"""
        raw = self._client.get(self._embedding_key(model, text))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    @_redis_guard(False)
    def set_embedding(self, model: str, text: str, vector: list[float], ttl_seconds: int) -> bool:
        """写入向量缓存（TTL 带抖动）。返回是否写入成功。"""
        self._client.setex(self._embedding_key(model, text), ttl_with_jitter(ttl_seconds), json.dumps(vector))
        return True

    # ── 分布式限流（滑动窗口 ZSET） ──────────────────────────────

    @_redis_guard((True, -1))
    def rate_limit_check(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """
        基于 Redis ZSET 的滑动窗口限流（进程间共享计数，多 worker 下结果一致）。

        🧠 算法：用「以请求时间戳为 score 的有序集合」当请求日志。每次请求一个 pipeline 内：
            1. ZREMRANGEBYSCORE 清掉滑出窗口的旧请求；
            2. ZADD 记入本次请求（member 唯一）；
            3. ZCARD 得到窗口内请求数；
            4. EXPIRE 给冷却 key 兜底回收。
            若超限，把刚加入的这条 ZREM 掉——不让被拒请求继续占空间/刷新窗口。

        🛡️ Redis 不可用时 `_redis_guard` 直接返回 (True, -1)：fail-open 放行，
            贯彻「Redis 非必须依赖、宕机不阻断主流程」。返回 (allowed, remaining)，
            remaining=-1 表示降级放行、额度未知。

        ⚠️ 该「先加后判、超限再撤」属滑动窗口日志法；极端并发下 pipeline 与补偿 ZREM
            之间可能临时多放行个别请求。要严格原子可改用 Lua 脚本（EVAL）一次完成判定，
            生产级实现可改用此法；此处优先保证可测与依赖最小。
        """
        now = time.time()
        member = f"{now:.6f}:{random.random()}"
        pipe = self._client.pipeline()
        pipe.zremrangebyscore(key, 0, now - window_seconds)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, int(window_seconds) + 1)
        count = pipe.execute()[2]
        if count > limit:
            self._client.zrem(key, member)
            return (False, 0)
        return (True, max(0, limit - count))

    # ── 三态熔断器共享态（多 worker 一致） ──────────────────────

    @_redis_guard(None)
    def breaker_on_failure(self, name: str, threshold: int, cooldown_seconds: int) -> str:
        """
        记一次失败：窗口内失败计数 +1（pipeline 内 INCR+EXPIRE），达阈值则写「熔断中」key
        （TTL=冷却期）。返回 'OPEN'（已熔断）/ 'CLOSED'（仍放行）。

        🧠 冷却期满后 fail/open 两个 key 一起过期 → 自动回到 CLOSED；过期后第一个请求会被
            breaker_allow 放行（等效 HALF_OPEN 探测），失败计数需重新累积到阈值才再次熔断。
        """
        fail_key = f"cb:fail:{name}"
        pipe = self._client.pipeline()
        pipe.incr(fail_key)
        pipe.expire(fail_key, cooldown_seconds)
        failures = pipe.execute()[0]
        if failures >= threshold:
            self._client.setex(f"cb:open:{name}", cooldown_seconds, "1")
            from core.observability.metrics import record_circuit_open

            record_circuit_open(name)
            return "OPEN"
        return "CLOSED"

    @_redis_guard(None)
    def breaker_on_success(self, name: str) -> None:
        """一次成功即清零：删失败计数与熔断标记，回到 CLOSED。"""
        self._client.delete(f"cb:fail:{name}", f"cb:open:{name}")

    @_redis_guard(True)
    def breaker_allow(self, name: str) -> bool:
        """是否放行：无「熔断中」key 即放行。Redis 不可用时 fail-open 放行。"""
        return not self._client.exists(f"cb:open:{name}")

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
