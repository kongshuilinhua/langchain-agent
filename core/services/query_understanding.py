from __future__ import annotations

import json
import re
from dataclasses import dataclass

# 意图标签
INTENT_KNOWLEDGE = "knowledge"
INTENT_TOOL = "tool"
INTENT_CHITCHAT = "chitchat"
VALID_INTENTS = {INTENT_KNOWLEDGE, INTENT_TOOL, INTENT_CHITCHAT}

# 路由标签
ROUTE_KNOWLEDGE = "knowledge"
ROUTE_TOOL = "tool"
ROUTE_CHITCHAT = "chitchat"
ROUTE_CLARIFY = "clarify"

_DEFAULT_CLARIFICATION = "我不太确定你的问题指向，可以补充说明一下你想了解什么吗？"

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def decide_route(intent: str, confidence: float, config: dict) -> tuple[str, str]:
    """根据意图与置信度裁决最终路由。

    返回 (route, clarification)。仅当 route==ROUTE_CLARIFY 时 clarification 非空。
    """
    normalized_intent = intent if intent in VALID_INTENTS else INTENT_KNOWLEDGE
    threshold = float(config.get("confidence_threshold", 0.5))
    clarify_enabled = bool(config.get("clarify_enabled", True))
    if clarify_enabled and float(confidence) < threshold:
        return ROUTE_CLARIFY, _DEFAULT_CLARIFICATION
    return normalized_intent, ""


def _parse_understanding(content: str) -> dict | None:
    """从 LLM 文本里抽取并解析第一个 JSON 对象，容忍代码围栏与前后噪声。"""
    if not content or not content.strip():
        return None
    match = _JSON_OBJECT_RE.search(content)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@dataclass
class QueryUnderstanding:
    rewritten_query: str
    intent: str
    confidence: float
    route: str
    clarification: str = ""
    applied: bool = True       # False 表示被禁用或降级，行为等价现状
    reason: str = "ok"         # ok | disabled | error

    def event_payload(self) -> dict:
        """SSE/前端展示用的精简载荷。"""
        return {
            "applied": self.applied,
            "intent": self.intent,
            "confidence": self.confidence,
            "route": self.route,
            "rewritten_query": self.rewritten_query,
            "reason": self.reason,
        }


def _passthrough(user_message: str, *, reason: str) -> QueryUnderstanding:
    """降级/禁用时的兜底：等价于现有「直接走 knowledge + 原始 query」行为。"""
    return QueryUnderstanding(
        rewritten_query=user_message,
        intent=INTENT_KNOWLEDGE,
        confidence=1.0,
        route=ROUTE_KNOWLEDGE,
        clarification="",
        applied=False,
        reason=reason,
    )


def _build_messages(user_message: str, history: list[dict], history_turns: int) -> list[dict]:
    """构造改写 + 分类的单次调用消息。"""
    recent = history[-history_turns:] if history else []
    history_text = "\n".join(
        f"用户：{turn.get('user', '')}\n助手：{turn.get('assistant', '')}" for turn in recent
    ) or "（无历史）"
    system = (
        "你是一个查询理解器。基于对话历史，把用户的最新问题改写成不依赖上下文的自包含问题，"
        "并判断意图。只输出一个 JSON 对象，不要任何额外文字。\n"
        "字段：rewritten_query(字符串)、intent(knowledge/tool/chitchat 三选一)、confidence(0~1 浮点)。\n"
        "intent 含义：knowledge=需要查知识库；tool=需要调用业务工具/执行动作；chitchat=寒暄或与知识无关的闲聊。"
    )
    user = f"对话历史：\n{history_text}\n\n用户最新问题：{user_message}\n\n请输出 JSON。"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def analyze(
    provider,
    *,
    user_message: str,
    history: list[dict],
    config: dict,
    runtime_config: dict | None = None,
) -> QueryUnderstanding:
    """查询理解编排入口。任何异常都降级为 passthrough，绝不抛出。"""
    if not config.get("enabled", True):
        return _passthrough(user_message, reason="disabled")
    try:
        messages = _build_messages(user_message, history or [], int(config.get("history_turns", 4)))
        response = provider.chat(
            messages,
            model=config.get("model"),
            temperature=0.0,
            runtime_config=runtime_config,
        )
        data = _parse_understanding(response.content or "")
        if not data:
            return _passthrough(user_message, reason="error")
        rewritten = str(data.get("rewritten_query") or "").strip() or user_message
        intent = str(data.get("intent") or INTENT_KNOWLEDGE).strip().lower()
        confidence = float(data.get("confidence", 1.0))
        route, clarification = decide_route(intent, confidence, config)
        return QueryUnderstanding(
            rewritten_query=rewritten,
            intent=intent if intent in VALID_INTENTS else INTENT_KNOWLEDGE,
            confidence=confidence,
            route=route,
            clarification=clarification,
            applied=True,
            reason="ok",
        )
    except Exception:
        return _passthrough(user_message, reason="error")
