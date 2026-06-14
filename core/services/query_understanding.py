from __future__ import annotations

import json
import re

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
