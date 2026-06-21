from __future__ import annotations


def get_chat_model(*, model=None, temperature=0.0, runtime_config=None, **kwargs):
    """返回与原生 OpenAICompatibleProvider 指向相同端点的 ChatOpenAI。"""
    from langchain_openai import ChatOpenAI

    from core.config import get_settings
    from core.integrations.llm import OpenAICompatibleProvider

    settings = get_settings()
    provider = OpenAICompatibleProvider()
    api_key = provider._api_key(settings, runtime_config, purpose="chat")
    base_url = provider._api_base(settings, runtime_config, purpose="chat")
    resolved_model = model or (runtime_config or {}).get("chat_model") or settings.openai_model
    return ChatOpenAI(
        model=resolved_model,
        base_url=base_url,
        api_key=api_key or "x",
        temperature=temperature,
        **kwargs,
    )
