from core.services.query_understanding import (
    QueryUnderstanding,
    QueryUnderstandingResult,
    _analyze_langchain,
    analyze,
)


class _FakeStructuredModel:
    def __init__(self, *, result=None, error=None):
        self.result = result
        self.error = error
        self.schema = None
        self.method = None
        self.messages = None

    def with_structured_output(self, schema, *, method):
        self.schema = schema
        self.method = method
        return self

    def invoke(self, messages):
        self.messages = messages
        if self.error:
            raise self.error
        return self.result


def test_analyze_langchain_returns_structured_dict(monkeypatch):
    fake = _FakeStructuredModel(
        result=QueryUnderstandingResult(
            rewritten_query="产品 X 的保修期",
            intent="knowledge",
            confidence=0.93,
        )
    )
    monkeypatch.setattr("core.integrations.langchain_provider.get_chat_model", lambda **kwargs: fake)
    messages = [{"role": "user", "content": "保修多久"}]

    result = _analyze_langchain(messages, model="test-model", runtime_config={"base_url": "test"})

    assert result == {
        "rewritten_query": "产品 X 的保修期",
        "intent": "knowledge",
        "confidence": 0.93,
    }
    assert fake.schema is QueryUnderstandingResult
    assert fake.method == "function_calling"
    assert fake.messages == messages


def test_analyze_langchain_returns_none_on_exception(monkeypatch):
    fake = _FakeStructuredModel(error=RuntimeError("model down"))
    monkeypatch.setattr("core.integrations.langchain_provider.get_chat_model", lambda **kwargs: fake)

    assert _analyze_langchain([], model=None, runtime_config=None) is None


def test_analyze_langchain_parser_returns_query_understanding(monkeypatch):
    fake = _FakeStructuredModel(
        result=QueryUnderstandingResult(
            rewritten_query="创建售后工单",
            intent="tool",
            confidence=0.95,
        )
    )
    monkeypatch.setattr("core.integrations.langchain_provider.get_chat_model", lambda **kwargs: fake)
    config = {
        "enabled": True,
        "parser": "langchain",
        "model": "test-model",
        "confidence_threshold": 0.5,
        "clarify_enabled": True,
        "history_turns": 4,
    }

    result = analyze(object(), user_message="帮我报修", history=[], config=config)

    assert isinstance(result, QueryUnderstanding)
    assert result.applied is True
    assert result.intent == "tool"
    assert result.route == "tool"
    assert result.rewritten_query == "创建售后工单"


def test_analyze_langchain_parser_degrades_to_passthrough(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("unsupported structured output")

    monkeypatch.setattr("core.integrations.langchain_provider.get_chat_model", fail)
    config = {
        "enabled": True,
        "parser": "langchain",
        "confidence_threshold": 0.5,
        "clarify_enabled": True,
        "history_turns": 4,
    }

    result = analyze(object(), user_message="原始问题", history=[], config=config)

    assert result.applied is False
    assert result.reason == "error"
    assert result.route == "knowledge"
    assert result.rewritten_query == "原始问题"
