from __future__ import annotations

import hashlib
import json
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field

from core.config import get_settings
from core.integrations.circuit_breaker import CircuitBreaker

# 🎯 系统硬编码默认的 OpenAI 兼容模式 API 端点（指向阿里云百炼/通义千问兼容接口）
DASHSCOPE_COMPATIBLE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
OPENAI_COMPATIBLE_DEFAULT_BASE = DASHSCOPE_COMPATIBLE_BASE


@dataclass
class ChatResponse:
    """
    统一的智能体文本响应实体类。
    
    🎯 意图与工程大局观：
        抹平各大模型厂商返回格式的微观差异，为上层 Agent 提供标准格式。
        支持携带内容 `content` 和工具调用列表 `tool_calls`。
    """
    content: str | None = None
    tool_calls: list[dict] | None = None


class OpenAICompatibleProvider:
    """
    标准 OpenAI 兼容模型提供商。

    🎯 意图与工程大局观：
        系统底层唯一且核心的通用 LLM 交互客户端。
        不仅支持同步问答（chat）、流式输出（chat_stream）、文本嵌入（embed），还前瞻性地内置了标准 RAG 重排器（rerank）接口。
        
    🛡️ 防御性设计：
        - 完全基于 Python 原生库 `urllib.request` 实现，不引入 `requests` 或 `httpx` 等外部网络库，保证系统核心引擎的极致轻量化与高可移植性。
        - 深度融合了测试开发模式（mock_llm），在没有 API 密钥或处于脱机开发测试场景下自动进行仿真响应，极大提升了测试反馈速度。
    """

    def __init__(self) -> None:
        # 🛡️ 调试标记：记录上一次交互是否由 Mock 仿真模块接管，便于单元测试进行状态断言
        self.last_chat_mock = False
        self.last_embed_mock = False
        # 🛡️ 三态熔断器：每个模型独立追踪健康状态（参考 Ragent 设计）
        self._breakers: dict[str, CircuitBreaker] = {}

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.4,
        runtime_config: dict | None = None,
        tools: list[dict] | None = None,
    ) -> ChatResponse:
        """
        同步文本生成方法（支持 Tool Call 参数请求）。

        🧠 魔鬼数字与前沿技术参数：
            - `temperature` 默认 0.4: 处于确定性回答与创造性逻辑的均衡点，适合严谨的 Agent 编排流转。
            - 针对 Mock 模式，工具调用仿真生成确定性的哈希值作为 call_id，方便前后端状态回溯。
        
        🛡️ 防御性编程：
            - 对空 API_KEY 在执行前进行前置检查，避免发出无谓的 HTTP 请求。
        """
        settings = get_settings()
        api_key = self._api_key(settings, runtime_config, purpose="chat")
        if settings.mock_llm:
            self.last_chat_mock = True
            user_text = self._content_text(next((m["content"] for m in reversed(messages) if m.get("role") == "user"), ""))
            context_hint = " ".join(self._content_text(m.get("content", ""))[:160] for m in messages if m.get("role") == "system")
            if tools:
                tool_names = [t.get("function", {}).get("name", "") for t in tools]
                return ChatResponse(
                    tool_calls=[{
                        "id": f"mock_call_{hashlib.md5(user_text.encode()).hexdigest()[:8]}",
                        "type": "function",
                        "function": {"name": tool_names[0], "arguments": json.dumps({"query": user_text[:120]}, ensure_ascii=False)},
                    }]
                )
            return ChatResponse(content=f"Mock answer for: {user_text}\n\nContext summary: {context_hint[:220]}")
        if not api_key:
            raise RuntimeError("Chat model API key is not configured")
        self.last_chat_mock = False

        # 🛡️ 熔断器检查：模型不可用时快速失败
        model_name = model or (runtime_config or {}).get("chat_model") or settings.openai_model
        breaker = self._breaker_for(model_name)
        if not breaker.allow_request():
            raise RuntimeError(f"Model '{model_name}' is temporarily unavailable (circuit breaker open)")

        url = self._api_base(settings, runtime_config, purpose="chat").rstrip("/") + "/chat/completions"
        payload: dict = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            data = self._post_json(url, payload, api_key)
        except Exception:
            breaker.record_failure()
            raise
        breaker.record_success()
        return self._parse_chat_response(data)

    def chat_stream(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.4,
        runtime_config: dict | None = None,
        tools: list[dict] | None = None,
    ) -> Iterable[str]:
        """
        异步流式文本生成生成器（Server-Sent Events）。

        ⚡ 边界与性能思考：
            - 利用 Python 的 `yield` 关键字返回生成器，支持逐字/逐词流式推送到前端，显著降低用户端首字延迟（TTFT）。
            - 流式输出在大批量并发处理下，能大幅平抑服务器网络 I/O 峰值吞吐，优化瞬时带宽占用。
        """
        settings = get_settings()
        api_key = self._api_key(settings, runtime_config, purpose="chat")
        if settings.mock_llm:
            self.last_chat_mock = True
            text = self.chat(messages, model=model, temperature=temperature, runtime_config=runtime_config, tools=tools)
            if text.tool_calls:
                yield json.dumps({"tool_calls": text.tool_calls}, ensure_ascii=False)
                return
            for index in range(0, len(text.content or ""), 24):
                yield (text.content or "")[index : index + 24]
            return
        if not api_key:
            raise RuntimeError("Chat model API key is not configured")
        self.last_chat_mock = False

        # 🛡️ 熔断器检查：模型不可用时快速失败
        model_name = model or (runtime_config or {}).get("chat_model") or settings.openai_model
        breaker = self._breaker_for(model_name)
        if not breaker.allow_request():
            raise RuntimeError(f"Model '{model_name}' is temporarily unavailable (circuit breaker open)")

        url = self._api_base(settings, runtime_config, purpose="chat").rstrip("/") + "/chat/completions"
        payload: dict = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        # 🎯 编排流转：有工具绑定时，实际上由工作流 runtime 模块使用非流式 chat() 做决策，流式仅在最后的最终回答生成阶段触发
        try:
            yield from self._post_json_stream(url, payload, api_key)
        except Exception:
            breaker.record_failure()
            raise
        breaker.record_success()

    def embed(self, text: str, *, runtime_config: dict | None = None) -> list[float]:
        """
        文本向量化嵌入（Embedding）。

        🧠 魔鬼数字与前沿技术参数：
            - Mock 向量生成机制：输出 32 维特征向量（数值区间为 [-1.0, 1.0]），确保能够被相似度计算方法（IP / Cosine）正常解析。
        """
        settings = get_settings()
        api_key = self._api_key(settings, runtime_config, purpose="embedding")
        if settings.mock_llm:
            self.last_embed_mock = True
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            return [((digest[i % len(digest)] / 255.0) * 2) - 1 for i in range(32)]
        if not api_key:
            raise RuntimeError("Embedding API key is not configured")
        self.last_embed_mock = False

        url = self._api_base(settings, runtime_config, purpose="embedding").rstrip("/") + "/embeddings"
        payload = {"model": settings.openai_embedding_model, "input": text}
        data = self._post_json(url, payload, api_key)
        return data["data"][0]["embedding"]

    def rerank(self, query: str, documents: list[str], *, top_n: int | None = None, model: str | None = None) -> list[dict]:
        """
        RAG 检索重排（Rerank）。

        🎯 意图与工程大局观：
            - 提供针对召回知识文档的深度语义相关性评估。向量检索侧重粗筛，而重排利用精细的 Cross-Encoder 模型做精准打分，极大缓解大模型长上下文带来的“迷失在中间（Lost in the Middle）”问题。
            
        🛡️ 防御性设计：
            - 当传入文档列表为空时，直接短路返回空列表，避免向模型网关发出空负载请求。
            - 自动兼容第三方 Rerank 厂商非标的输出格式（如 `index`/`document_index`、`relevance_score`/`rank_score` 等各种 JSON 字段变体）。
        """
        settings = get_settings()
        api_key = self._api_key(settings, purpose="rerank")
        if not documents:
            return []
        if settings.mock_llm:
            query_terms = {term.lower() for term in query.split() if term.strip()}
            ranked = []
            for index, document in enumerate(documents):
                text = document.lower()
                score = sum(1 for term in query_terms if term in text) / max(len(query_terms), 1)
                ranked.append({"index": index, "relevance_score": float(score)})
            return sorted(ranked, key=lambda item: item["relevance_score"], reverse=True)[: top_n or len(documents)]
        if not api_key:
            raise RuntimeError("Rerank API key is not configured")

        url = self._api_base(settings, purpose="rerank").rstrip("/") + "/rerank"
        payload = {
            "model": model or settings.rag_rerank_model,
            "query": query,
            "documents": documents,
            **({"top_n": top_n} if top_n else {}),
        }
        data = self._post_json(url, payload, api_key)
        results = data.get("results") or data.get("data") or []
        normalized = []
        for item in results:
            if not isinstance(item, dict):
                continue
            index = item.get("index", item.get("document_index"))
            if index is None:
                document = item.get("document")
                if document in documents:
                    index = documents.index(document)
            if index is None:
                continue
            score = item.get("relevance_score", item.get("score", item.get("rank_score", 0)))
            normalized.append({"index": int(index), "relevance_score": float(score or 0)})
        return normalized[: top_n or len(normalized)]

    # ── 私有辅助方法群 ──────────────────────────────────────────

    def _parse_chat_response(self, data: dict) -> ChatResponse:
        """
        解析并抽取模型返回的数据报文。
        
        🛡️ 防御性设计：
            - 利用极度安全的字典 `get` 级联，提供全面的降级默认值，确保就算模型返回了缺失某字段的不良报文，系统也不会产生 KeyError 级物理崩溃。
        """
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        raw_tool_calls = message.get("tool_calls") or []
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                func = tc.get("function") or {}
                tool_calls.append({
                    "id": tc.get("id") or "",
                    "type": tc.get("type") or "function",
                    "function": {
                        "name": func.get("name") or "",
                        "arguments": func.get("arguments") or "{}",
                    },
                })
            return ChatResponse(content=content or None, tool_calls=tool_calls)
        return ChatResponse(content=str(content) if content else "")

    def _api_key(self, settings, runtime_config: dict | None = None, *, purpose: str = "chat") -> str | None:
        """
        多路 API Key 路由解析器。
        
        🎯 意图与工程大局观：
            - 按优先级解析：用户私有模型 BYOK 传入密钥 -> 全局各厂商（Embedding/Rerank/DeepSeek/DashScope）专属环境变量 -> 通用 OpenAI 兼容变量，实现无感的多引擎自适应接入。
        """
        if runtime_config and purpose == "chat" and runtime_config.get("api_key"):
            return str(runtime_config["api_key"]).strip() or None
        if purpose == "embedding" and settings.embedding_api_key:
            return settings.embedding_api_key.strip() or None
        if purpose == "rerank" and settings.rerank_api_key:
            return settings.rerank_api_key.strip() or None
        if purpose == "chat":
            base = (settings.openai_api_base or "").rstrip("/")
            if settings.dashscope_api_key and base == DASHSCOPE_COMPATIBLE_BASE.rstrip("/"):
                return settings.dashscope_api_key.strip() or None
            if settings.deepseek_api_key and (base == settings.deepseek_api_base.rstrip("/") or settings.openai_model == settings.deepseek_model):
                return settings.deepseek_api_key.strip() or None
            if settings.openai_api_key:
                return settings.openai_api_key.strip() or None
            return (settings.dashscope_api_key or settings.deepseek_api_key or "").strip() or None
        return (settings.openai_api_key or settings.dashscope_api_key or "").strip() or None

    def _api_base(self, settings, runtime_config: dict | None = None, *, purpose: str = "chat") -> str:
        """
        多路 API Base URL 路由解析器。
        """
        if runtime_config and purpose == "chat" and runtime_config.get("base_url"):
            return str(runtime_config["base_url"]).strip()
        if purpose == "embedding" and settings.embedding_api_base:
            return settings.embedding_api_base
        if purpose == "rerank" and settings.rerank_api_base:
            return settings.rerank_api_base
        if purpose == "chat" and settings.deepseek_api_key and (
            (settings.openai_api_base or "").rstrip("/") == settings.deepseek_api_base.rstrip("/")
            or settings.openai_model == settings.deepseek_model
        ):
            return settings.deepseek_api_base
        base = (settings.openai_api_base or "").strip()
        if settings.dashscope_api_key and (not base or base.rstrip("/") == OPENAI_COMPATIBLE_DEFAULT_BASE.rstrip("/")):
            return DASHSCOPE_COMPATIBLE_BASE
        return base or OPENAI_COMPATIBLE_DEFAULT_BASE

    def _breaker_for(self, model_name: str) -> CircuitBreaker:
        """获取指定模型的熔断器实例（惰性创建）。"""
        if model_name not in self._breakers:
            self._breakers[model_name] = CircuitBreaker(failure_threshold=3, timewindow=60)
        return self._breakers[model_name]

    def _post_json(self, url: str, payload: dict, api_key: str, *, timeout_seconds: int = 60) -> dict:
        """
        同步 POST JSON 工具函数。

        🧠 魔鬼数字与前沿技术参数：
            - `timeout_seconds` 默认 60: 适合处理大模型首字延迟或较复杂的工具推理时常，防止网络波动导致提前熔断。
        
        🛡️ 防御性设计：
            - 在异常处理（urllib.error.HTTPError）中，使用 `[:800]` 截断大段的报错包体，防止大篇幅无意义的 HTML/JSON 报错直接撑爆控制台日志系统。
            - 针对底层各种网络抖动、Socket 超时、SSL 握手异常或 OS 系统层异常进行全包围式的 Try-Catch 捕获，并转化为统一的工程化 RuntimeError。
        """
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise RuntimeError(
                f"Model call failed: HTTP {exc.code}. Check OPENAI_API_BASE, API key and model name. {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError, OSError) as exc:
            raise RuntimeError(
                f"Model call failed: cannot connect to model gateway {url}. Check OPENAI_API_BASE, proxy, certs and API key. Raw error: {exc}"
            ) from exc

    def _post_json_stream(self, url: str, payload: dict, api_key: str) -> Iterable[str]:
        """
        纯 Python 原生 SSE（Server-Sent Events）解析流式输出生成器。

        🛡️ 防御性设计：
            - `Accept` 字段指定为 "text/event-stream" 触发流式模式。
            - 过滤非数据行或空行，智能忽略并容错无法被 JSON 反序列化的碎片行。
            - 处理 EOF 状态：接收到 `[DONE]` 字符后，优雅退出流式生成，阻断无用的后续空循环读取。
        """
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload_text = line.removeprefix("data:").strip()
                    if payload_text == "[DONE]":
                        break
                    try:
                        data = json.loads(payload_text)
                    except json.JSONDecodeError:
                        continue
                    token = self._stream_delta(data)
                    if token:
                        yield token
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise RuntimeError(
                f"Model call failed: HTTP {exc.code}. Check OPENAI_API_BASE, API key and model name. {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError, OSError) as exc:
            raise RuntimeError(
                f"Model call failed: cannot connect to model gateway {url}. Check OPENAI_API_BASE, proxy, certs and API key. Raw error: {exc}"
            ) from exc

    def _stream_delta(self, data: dict) -> str:
        """
        流式消息碎片字段定位处理器。
        
        🛡️ 防御性设计：
            - 精细解析 OpenAI 的 delta 字段，兼容不同的 delta 报文返回，包括支持列表变体 `choices[0].delta.content`，避免多厂商细微差异引起的解析异常崩溃。
        """
        choices = data.get("choices") or []
        if not choices:
            return ""
        first = choices[0] or {}
        delta = first.get("delta") or {}
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                return "".join(parts)
        message = first.get("message") or {}
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        text = first.get("text")
        return text if isinstance(text, str) else ""

    def _content_text(self, content) -> str:
        """
        标准/多模态消息包体文本化抽取。
        
        🛡️ 防御性设计：
            - 智能抹平字符串与 OpenAI 多模态列表结构（List of dicts containing image_url and text）的格式差异，保障系统在遇到多模态输入时能稳定降级提取用于哈希或元数据分析的文本。
        """
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif isinstance(item, dict) and item.get("type") == "image_url":
                    parts.append("[image]")
            return " ".join(parts)
        return str(content)
