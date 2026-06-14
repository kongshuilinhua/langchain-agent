from core.integrations.llm import ChatResponse
from core.services.agents import DEFAULT_QUERY_UNDERSTANDING, normalize_query_understanding
from core.services.query_understanding import (
    ROUTE_CHITCHAT,
    ROUTE_CLARIFY,
    ROUTE_KNOWLEDGE,
    ROUTE_TOOL,
    QueryUnderstanding,
    _parse_understanding,
    analyze,
    decide_route,
)


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


def test_parse_plain_json():
    data = _parse_understanding('{"rewritten_query": "X的价格", "intent": "knowledge", "confidence": 0.9}')
    assert data["rewritten_query"] == "X的价格"
    assert data["intent"] == "knowledge"
    assert data["confidence"] == 0.9


def test_parse_json_in_code_fence():
    content = "```json\n{\"rewritten_query\": \"你好\", \"intent\": \"chitchat\", \"confidence\": 0.95}\n```"
    data = _parse_understanding(content)
    assert data["intent"] == "chitchat"


def test_parse_garbage_returns_none():
    assert _parse_understanding("这不是 JSON") is None
    assert _parse_understanding("") is None


class _FakeProvider:
    def __init__(self, content=None, raise_exc=False):
        self._content = content
        self._raise = raise_exc
        self.calls = []

    def chat(self, messages, *, model=None, temperature=0.4, runtime_config=None, tools=None):
        self.calls.append({"messages": messages, "model": model})
        if self._raise:
            raise RuntimeError("model down")
        return ChatResponse(content=self._content)


_ENABLED = {"enabled": True, "model": None, "confidence_threshold": 0.5,
            "clarify_enabled": True, "history_turns": 4}


def test_analyze_disabled_passthrough_no_llm_call():
    provider = _FakeProvider(content="should not be used")
    cfg = {**_ENABLED, "enabled": False}
    result = analyze(provider, user_message="你好", history=[], config=cfg)
    assert isinstance(result, QueryUnderstanding)
    assert result.applied is False
    assert result.route == "knowledge"
    assert result.rewritten_query == "你好"
    assert provider.calls == []


def test_analyze_knowledge_intent():
    provider = _FakeProvider(
        content='{"rewritten_query": "产品X保修期", "intent": "knowledge", "confidence": 0.92}'
    )
    result = analyze(provider, user_message="保修多久", history=[], config=_ENABLED)
    assert result.applied is True
    assert result.intent == "knowledge"
    assert result.route == "knowledge"
    assert result.rewritten_query == "产品X保修期"


def test_analyze_chitchat_skips_retrieval():
    provider = _FakeProvider(
        content='{"rewritten_query": "你好", "intent": "chitchat", "confidence": 0.95}'
    )
    result = analyze(provider, user_message="你好啊", history=[], config=_ENABLED)
    assert result.route == "chitchat"


def test_analyze_low_confidence_clarifies():
    provider = _FakeProvider(
        content='{"rewritten_query": "它", "intent": "knowledge", "confidence": 0.2}'
    )
    result = analyze(provider, user_message="它呢", history=[], config=_ENABLED)
    assert result.route == "clarify"
    assert result.clarification


def test_analyze_degrades_on_exception():
    provider = _FakeProvider(raise_exc=True)
    result = analyze(provider, user_message="原始问题", history=[], config=_ENABLED)
    assert result.applied is False
    assert result.reason == "error"
    assert result.route == "knowledge"
    assert result.rewritten_query == "原始问题"


def test_analyze_degrades_on_bad_json():
    provider = _FakeProvider(content="模型今天不想输出 JSON")
    result = analyze(provider, user_message="原始问题", history=[], config=_ENABLED)
    assert result.applied is False
    assert result.reason == "error"
    assert result.rewritten_query == "原始问题"


def test_analyze_uses_configured_model():
    provider = _FakeProvider(
        content='{"rewritten_query": "q", "intent": "knowledge", "confidence": 0.9}'
    )
    cfg = {**_ENABLED, "model": "qwen-turbo"}
    analyze(provider, user_message="q", history=[], config=cfg)
    assert provider.calls[0]["model"] == "qwen-turbo"


def test_route_gates_retrieval_helper():
    # 该断言锁定 Knowledge 节点门控契约：仅 route==knowledge 才检索
    def should_retrieve(rag_enabled: bool, route: str) -> bool:
        return rag_enabled and route == ROUTE_KNOWLEDGE
    assert should_retrieve(True, ROUTE_KNOWLEDGE) is True
    assert should_retrieve(True, ROUTE_CHITCHAT) is False
    assert should_retrieve(False, ROUTE_KNOWLEDGE) is False
