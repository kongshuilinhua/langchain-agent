import os
from types import SimpleNamespace

from core.integrations import langsmith_setup


def test_langsmith_settings_default_disabled(monkeypatch):
    from core.config import Settings

    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    settings = Settings(_env_file=None)

    assert settings.langsmith_tracing is False
    assert settings.langsmith_api_key is None
    assert settings.langsmith_project == "lingshu-agent"


def test_configure_langsmith_sets_environment_when_enabled(monkeypatch):
    fake_env = {}
    monkeypatch.setattr(os, "environ", fake_env)
    monkeypatch.setattr(
        "core.config.get_settings",
        lambda: SimpleNamespace(
            langsmith_tracing=True,
            langsmith_api_key="ls-test-key",
            langsmith_project="test-project",
        ),
    )
    assert langsmith_setup.configure_langsmith() is True
    assert fake_env["LANGSMITH_TRACING"] == "true"
    assert fake_env["LANGSMITH_API_KEY"] == "ls-test-key"
    assert fake_env["LANGSMITH_PROJECT"] == "test-project"


def test_configure_langsmith_does_not_mutate_environment_when_disabled(monkeypatch):
    fake_env = {"LANGSMITH_TRACING": "sentinel"}
    monkeypatch.setattr(os, "environ", fake_env)
    monkeypatch.setattr(
        "core.config.get_settings",
        lambda: SimpleNamespace(
            langsmith_tracing=False,
            langsmith_api_key="ls-test-key",
            langsmith_project="test-project",
        ),
    )
    assert langsmith_setup.configure_langsmith() is False
    assert fake_env["LANGSMITH_TRACING"] == "sentinel"


def test_configure_langsmith_requires_api_key(monkeypatch):
    fake_env = {}
    monkeypatch.setattr(os, "environ", fake_env)
    monkeypatch.setattr(
        "core.config.get_settings",
        lambda: SimpleNamespace(
            langsmith_tracing=True,
            langsmith_api_key=None,
            langsmith_project="test-project",
        ),
    )
    assert langsmith_setup.configure_langsmith() is False
    assert "LANGSMITH_TRACING" not in fake_env
