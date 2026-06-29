"""异步任务调度层单元测试（不依赖 celery / redis / 数据库）。

覆盖：
1. celery 不可用时回退 BackgroundTasks，并把 kwargs 原样转交；
2. celery 可用时按名投递到队列、不走回退；
3. 默认配置（CELERY_ENABLED 未开）下 build_celery_app() 返回 None。
"""

import os
import types

import pytest

from core.tasks import dispatch as dispatch_module


class FakeBackgroundTasks:
    def __init__(self) -> None:
        self.calls = []

    def add_task(self, func, **kwargs):
        self.calls.append((func, kwargs))


def test_falls_back_to_background_when_celery_absent(monkeypatch):
    monkeypatch.setattr(dispatch_module, "celery_app", None)
    bg = FakeBackgroundTasks()
    received = {}

    def fallback(**kwargs):
        received.update(kwargs)

    mode = dispatch_module.dispatch(
        bg, fallback, task_name="lingshu.ingest_document",
        document_id=1, workspace_id=2, kb_id=3,
    )

    assert mode == "background"
    assert bg.calls[0][1] == {"document_id": 1, "workspace_id": 2, "kb_id": 3}


def test_uses_celery_when_available(monkeypatch):
    sent = {}
    fake_app = types.SimpleNamespace(
        send_task=lambda name, kwargs: sent.update({"name": name, "kwargs": kwargs})
    )
    monkeypatch.setattr(dispatch_module, "celery_app", fake_app)
    bg = FakeBackgroundTasks()

    mode = dispatch_module.dispatch(
        bg, lambda **k: None, task_name="lingshu.reindex_kb",
        workspace_id=2, kb_id=3, job_id="kb-3-1",
    )

    assert mode == "celery"
    assert sent == {"name": "lingshu.reindex_kb", "kwargs": {"workspace_id": 2, "kb_id": 3, "job_id": "kb-3-1"}}
    assert bg.calls == []  # 回退路径未被触发


def test_build_returns_none_when_disabled():
    if os.getenv("CELERY_ENABLED", "").lower() in ("1", "true", "yes"):
        pytest.skip("CELERY_ENABLED 已在环境中开启，跳过默认禁用断言")
    from core.tasks.celery_app import build_celery_app

    assert build_celery_app() is None
