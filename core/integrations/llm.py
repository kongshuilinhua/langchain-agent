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

DASHSCOPE_COMPATIBLE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
OPENAI_COMPATIBLE_DEFAULT_BASE = DASHSCOPE_COMPATIBLE_BASE


@dataclass
class ChatResponse:
    content: str | None = None
    tool_calls: list[dict] | None = None


class OpenAICompatibleProvider:
    """Small OpenAI-compatible client with function calling support."""

    def __init__(self) -> None:
        self.last_chat_mock = False
        self.last_embed_mock = False

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.4,
        runtime_config: dict | None = None,
        tools: list[dict] | None = None,
    ) -> ChatResponse:
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

        url = self._api_base(settings, runtime_config, purpose="chat").rstrip("/") + "/chat/completions"
        payload: dict = {
            "model": model or (runtime_config or {}).get("chat_model") or settings.openai_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        data = self._post_json(url, payload, api_key)
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

        url = self._api_base(settings, runtime_config, purpose="chat").rstrip("/") + "/chat/completions"
        payload: dict = {
            "model": model or (runtime_config or {}).get("chat_model") or settings.openai_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        # When tools are present, stream normally — the caller (agent loop)
        # uses non-streaming chat() for tool-call decisions, so stream is
        # only for the final answer phase.
        yield from self._post_json_stream(url, payload, api_key)

    def embed(self, text: str, *, runtime_config: dict | None = None) -> list[float]:
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

    # ── private helpers ──────────────────────────────────────────

    def _parse_chat_response(self, data: dict) -> ChatResponse:
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

    def _post_json(self, url: str, payload: dict, api_key: str, *, timeout_seconds: int = 60) -> dict:
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
