"""facts 进程内召回（recall_facts）单元测试——hermetic，不依赖 Milvus / DB。

验证 Option B：召回由「直连 Milvus（受状态/最终一致性/跨环境残留影响，无阈值）」改为
「进程内 embedding 余弦 + 阈值」后，结果确定可控：无关 query 不召回、精确命中召回。
"""

from types import SimpleNamespace

import pytest


@pytest.fixture()
def mock_recall_env(monkeypatch):
    monkeypatch.setenv("LINGSHU_MOCK_LLM", "true")
    monkeypatch.setenv("MEMORY_RECALL_MIN_SCORE", "0.5")
    import core.config

    core.config.get_settings.cache_clear()
    yield
    core.config.get_settings.cache_clear()


def test_unrelated_query_not_recalled(mock_recall_env):
    from core.services.memory import recall_facts

    profile = SimpleNamespace(enabled=True, facts=["The user owns an S10 sweeper."])
    # mock embedding 下 cos("use my memory", fact)=0.2758 < 0.5 → 不召回
    assert recall_facts(profile, "use my memory", k=5) == []


def test_exact_match_recalled(mock_recall_env):
    from core.services.memory import recall_facts

    fact = "The user owns an S10 sweeper."
    profile = SimpleNamespace(enabled=True, facts=[fact])
    recalled = recall_facts(profile, fact, k=5)  # cos=1.0 ≥ 0.5
    assert len(recalled) == 1 and recalled[0]["text"] == fact


def test_disabled_or_empty_profile(mock_recall_env):
    from core.services.memory import recall_facts

    assert recall_facts(SimpleNamespace(enabled=False, facts=["x"]), "x", 5) == []
    assert recall_facts(SimpleNamespace(enabled=True, facts=[]), "x", 5) == []
    assert recall_facts(None, "x", 5) == []


def test_blank_query_returns_topk(mock_recall_env):
    from core.services.memory import recall_facts

    profile = SimpleNamespace(enabled=True, facts=["a fact", "b fact", "c fact"])
    # 空 query 不做相似度，直接回前 k 条
    assert len(recall_facts(profile, "   ", k=2)) == 2
