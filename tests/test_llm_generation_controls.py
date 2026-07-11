from types import SimpleNamespace

from core.integrations import llm as llm_module


def _settings(**overrides):
    data = {
        "mock_llm": False,
        "openai_api_base": "https://api.siliconflow.cn/v1",
        "openai_api_key": "test-key",
        "openai_model": "Qwen/Qwen3.5-122B-A10B",
        "dashscope_api_key": None,
        "deepseek_api_base": "https://api.deepseek.com",
        "deepseek_api_key": None,
        "deepseek_model": "deepseek-chat",
        "llm_max_tokens": 8192,
        "circuit_breaker_distributed": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_chat_disables_qwen3_thinking_by_default(monkeypatch):
    captured = {}
    provider = llm_module.OpenAICompatibleProvider()
    monkeypatch.setattr(llm_module, "get_settings", lambda: _settings())

    def fake_post(url, payload, api_key):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "4"}}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)

    provider.chat([{"role": "user", "content": "2+2"}])

    assert captured["payload"]["enable_thinking"] is False
    assert captured["payload"]["max_tokens"] == 8192


def test_chat_stream_allows_qwen3_thinking_when_requested(monkeypatch):
    captured = {}
    provider = llm_module.OpenAICompatibleProvider()
    monkeypatch.setattr(llm_module, "get_settings", lambda: _settings())

    def fake_stream(url, payload, api_key):
        captured["payload"] = payload
        yield "ok"

    monkeypatch.setattr(provider, "_post_json_stream", fake_stream)

    assert list(provider.chat_stream([{"role": "user", "content": "think"}], thinking=True)) == ["ok"]
    assert captured["payload"]["enable_thinking"] is True
    assert captured["payload"]["max_tokens"] == 8192


def test_enable_thinking_is_not_sent_to_unknown_provider(monkeypatch):
    captured = {}
    provider = llm_module.OpenAICompatibleProvider()
    monkeypatch.setattr(
        llm_module,
        "get_settings",
        lambda: _settings(openai_api_base="https://provider.example/v1", openai_model="plain-model"),
    )

    def fake_post(url, payload, api_key):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(provider, "_post_json", fake_post)

    provider.chat([{"role": "user", "content": "hello"}])

    assert "enable_thinking" not in captured["payload"]
    assert captured["payload"]["max_tokens"] == 8192


def test_stream_delta_skips_reasoning_content():
    """思考流不得混入回答 token（否则会被拼进 draft 存库并展示）。"""
    provider = llm_module.OpenAICompatibleProvider()

    token = provider._stream_delta({"choices": [{"delta": {"reasoning_content": "thinking..."}}]})

    assert token == ""


def test_stream_delta_reads_normal_content():
    provider = llm_module.OpenAICompatibleProvider()

    token = provider._stream_delta({"choices": [{"delta": {"content": "4"}}]})

    assert token == "4"
