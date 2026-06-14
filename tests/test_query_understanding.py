from core.services.agents import normalize_query_understanding, DEFAULT_QUERY_UNDERSTANDING


def test_normalize_defaults_on_empty():
    result = normalize_query_understanding(None)
    assert result == DEFAULT_QUERY_UNDERSTANDING


def test_normalize_clamps_threshold_and_turns():
    result = normalize_query_understanding(
        {"confidence_threshold": 5, "history_turns": 999, "enabled": False}
    )
    assert result["confidence_threshold"] == 1.0
    assert result["history_turns"] == 12
    assert result["enabled"] is False


def test_normalize_blank_model_becomes_none():
    result = normalize_query_understanding({"model": "   "})
    assert result["model"] is None


from core.services.query_understanding import (
    decide_route,
    ROUTE_KNOWLEDGE,
    ROUTE_TOOL,
    ROUTE_CHITCHAT,
    ROUTE_CLARIFY,
)

_CFG = {"confidence_threshold": 0.5, "clarify_enabled": True}


def test_decide_route_high_confidence_passthrough():
    assert decide_route("knowledge", 0.9, _CFG)[0] == ROUTE_KNOWLEDGE
    assert decide_route("tool", 0.8, _CFG)[0] == ROUTE_TOOL
    assert decide_route("chitchat", 0.7, _CFG)[0] == ROUTE_CHITCHAT


def test_decide_route_low_confidence_clarifies():
    route, clarification = decide_route("knowledge", 0.2, _CFG)
    assert route == ROUTE_CLARIFY
    assert clarification  # 非空澄清文本


def test_decide_route_low_confidence_without_clarify_falls_back():
    cfg = {"confidence_threshold": 0.5, "clarify_enabled": False}
    assert decide_route("tool", 0.1, cfg)[0] == ROUTE_TOOL


def test_decide_route_unknown_intent_defaults_knowledge():
    assert decide_route("garbage", 0.9, _CFG)[0] == ROUTE_KNOWLEDGE
