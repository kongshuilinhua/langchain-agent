from __future__ import annotations


def configure_langsmith() -> bool:
    """配置 LangSmith 自动追踪环境；仅在显式开启且提供 key 时生效。"""
    from core.config import get_settings

    settings = get_settings()
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        return False

    import os

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    return True
