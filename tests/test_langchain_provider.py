from types import SimpleNamespace

from core.integrations.langchain_provider import get_chat_model


def _settings():
    return SimpleNamespace(
        # 这两个用例验证真实 ChatOpenAI 路径，需显式关掉 mock，否则 get_chat_model 走 MockChatOpenAI 分支
        mock_llm=False,
        openai_api_base="https://provider.example/v1",
        openai_api_key="test-key",
        openai_model="settings-model",
        dashscope_api_key=None,
        deepseek_api_base="https://api.deepseek.com",
        deepseek_api_key=None,
        deepseek_model="deepseek-chat",
    )


def test_get_chat_model_uses_explicit_model_and_settings_base(monkeypatch):
    monkeypatch.setattr("core.config.get_settings", _settings)

    chat = get_chat_model(model="explicit-model")

    assert chat.model_name == "explicit-model"
    assert str(chat.openai_api_base) == "https://provider.example/v1"


def test_get_chat_model_uses_runtime_config_overrides(monkeypatch):
    monkeypatch.setattr("core.config.get_settings", _settings)
    runtime_config = {
        "chat_model": "runtime-model",
        "base_url": "https://runtime.example/v1",
        "api_key": "runtime-key",
    }

    chat = get_chat_model(runtime_config=runtime_config)

    assert chat.model_name == "runtime-model"
    assert str(chat.openai_api_base) == "https://runtime.example/v1"
