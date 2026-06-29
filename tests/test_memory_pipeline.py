# -*- coding: utf-8 -*-
import uuid
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock, patch

import core.db.session as db_session
import core.config
from core.db.models import SessionMemory, AgentMemoryProfile, Session as DbSession, Agent, User, Workspace
from core.runtime.memory_pipeline import run_memory_pipeline, ExtractedMemory
from core.services.memory import recall_profile_memory, recall_facts, get_memory_profile


def test_memory_pipeline_compaction_and_extraction(client, monkeypatch):
    """测试记忆管道在 MEMORY_LONG_TERM_EXTRACT 开启时的短期压缩与长期自动抽取。"""
    # 从重新加载后的 db_session 获取 SessionLocal，避免连接池中已被清理的连接导致 Lost Connection 报错
    db = db_session.SessionLocal()
    
    import core.config
    # 模拟环境配置开启长效抽取
    monkeypatch.setenv("MEMORY_LONG_TERM_EXTRACT", "true")
    monkeypatch.setenv("LINGSHU_MOCK_LLM", "true")
    monkeypatch.setenv("MEMORY_TOKEN_BUDGET", "0")
    core.config.get_settings.cache_clear()
    
    unique_id = uuid.uuid4().hex[:8]
    try:
        # 1. 创建基础测试数据：Workspace -> User -> Agent -> Session
        workspace = Workspace(name="Test Workspace", slug=f"test-workspace-{unique_id}")
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
        
        user = User(name="test_user", email=f"test-{unique_id}@example.com", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        
        agent = Agent(
            workspace_id=workspace.id,
            name="Test Agent",
            system_prompt="You are a helpful assistant.",
            model="mock-model",
            created_by=user.id,
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)
        
        session = DbSession(
            workspace_id=workspace.id,
            user_id=user.id,
            agent_id=agent.id,
            title="Pipeline Test Session",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        
        # 2. 模拟已有 SessionMemory 达到触发压缩 of token / 轮次限制
        # 构造 older_turns 让其触发压缩
        import json
        initial_turns = [{"user": f"user turn {i}", "assistant": f"assistant turn {i}"} for i in range(10)]
        session_mem = SessionMemory(
            session_id=session.id,
            summary=json.dumps({"summary": "", "turns": initial_turns}, ensure_ascii=False),
            message_count=20,
            version=0,
        )
        db.add(session_mem)
        db.commit()
        db.refresh(session_mem)
        
        # 3. 运行 memory_pipeline，并 mock get_chat_model 的 structured output
        # 我们 mock with_structured_output 返回自定义提取值以验证逻辑
        mock_extracted = ExtractedMemory(
            facts=["用户喜欢吃苹果", "用户是一名程序员"],
            preferences={"theme": "dark"}
        )
        
        class FakeStructuredRunnable:
            def invoke(self, messages, config=None):
                return mock_extracted
                
        class FakeChatModel:
            def with_structured_output(self, schema, **kwargs):
                return FakeStructuredRunnable()
                
        with patch("core.runtime.memory_pipeline.get_chat_model", return_value=FakeChatModel()):
            # 运行管道
            compaction_event = run_memory_pipeline(
                db=db,
                session_id=session.id,
                user_message="我叫小明",
                answer="你好小明",
                max_messages=6,  # 强制压缩
            )
            
            assert compaction_event["triggered"] is True
            
            # 4. 断言长期记忆 profile 已经自动生成并正确更新事实与偏好
            profile = get_memory_profile(db, workspace_id=workspace.id, user_id=user.id, agent_id=agent.id)
            assert profile is not None
            assert profile.enabled is True
            
            # 事实断言：应当包含刚才 mock 的 facts，且 source 应当为 "auto"
            facts = profile.facts
            assert len(facts) >= 2
            
            fact_texts = [f["text"] for f in facts]
            assert "用户喜欢吃苹果" in fact_texts
            assert "用户是一名程序员" in fact_texts
            
            # 检查 source 是否为 auto
            for f in facts:
                if f["text"] in ["用户喜欢吃苹果", "用户是一名程序员"]:
                    assert f["source"] == "auto"
                    
            # 偏好断言：应当正确更新 KV
            assert profile.preferences.get("theme") == "dark"
            
        pass
        
    finally:
        core.config.get_settings.cache_clear()
        db.close()


def test_recall_profile_memory_reuses_prerecalled_facts():
    """传入已召回的 facts 时不应再触发一次内部向量召回（避免同一回合重复 embedding + 检索）。"""
    profile = AgentMemoryProfile(
        workspace_id=1, user_id=1, agent_id=1,
        facts=[{"id": "1", "text": "全量里的事实", "source": "user",
                "created_at": datetime.now(timezone.utc).isoformat(), "score": 1.0}],
        preferences={},
        summary="摘要",
        enabled=True,
    )
    prerecalled = [{"id": "9", "text": "只该出现这条", "source": "auto",
                    "created_at": datetime.now(timezone.utc).isoformat(), "score": 1.0}]

    with patch("core.services.memory.recall_facts") as spy_recall:
        text = recall_profile_memory(profile, query="任意问题", k=3, facts=prerecalled)

    # 既不触发内部召回，又只拼装传入的 facts
    spy_recall.assert_not_called()
    assert "只该出现这条" in text
    assert "全量里的事实" not in text


def test_recall_profile_memory_fallback(client):
    """测试长期记忆召回兜底机制：embedding 调用失败时自动退回全量 facts 拼接（而非返回空）。

    召回已改为进程内 embedding 余弦相似度（不再依赖 Milvus），故兜底触发点由「Milvus 宕」
    改为「embedding 不可用」。"""
    # 从重新加载后的 db_session 获取 SessionLocal
    db = db_session.SessionLocal()
    unique_id = uuid.uuid4().hex[:8]
    try:
        # 创建合法的 workspace, user, agent 实例
        workspace = Workspace(name="Test Workspace 2", slug=f"test-workspace-{unique_id}")
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
        
        user = User(name="test_user_2", email=f"test-{unique_id}@example.com", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        
        agent = Agent(
            workspace_id=workspace.id,
            name="Test Agent 2",
            system_prompt="You are a helpful assistant.",
            model="mock-model",
            created_by=user.id,
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)

        # 创建临时 profile
        profile = AgentMemoryProfile(
            workspace_id=workspace.id,
            user_id=user.id,
            agent_id=agent.id,
            facts=[
                {"id": "1", "text": "我是杭州人", "source": "user", "created_at": datetime.now(timezone.utc).isoformat(), "score": 1.0},
                {"id": "2", "text": "我平时写Python", "source": "auto", "created_at": datetime.now(timezone.utc).isoformat(), "score": 1.0},
            ],
            preferences={"language": "Python"},
            summary="这是长期摘要说明",
            enabled=True,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        
        # 模拟 embedding 调用失败：召回应优雅退回全量 facts（取 top-k）而非返回空
        with patch("core.integrations.llm.OpenAICompatibleProvider.embed", side_effect=Exception("embedding failed")):
            recalled_text = recall_profile_memory(profile, query="你写什么语言？", k=5)

            # 应该降级回全量拼接，包含所有的 facts 和 preferences
            assert "Long-term memory summary:" in recalled_text
            assert "这是长期摘要说明" in recalled_text
            assert "我是杭州人" in recalled_text
            assert "我平时写Python" in recalled_text
            assert "language: Python" in recalled_text
            
        pass
    finally:
        core.config.get_settings.cache_clear()
        db.close()
