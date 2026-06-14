from __future__ import annotations

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
