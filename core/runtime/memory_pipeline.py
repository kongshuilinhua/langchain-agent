# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TypedDict, Optional, List, Dict, Any
from sqlalchemy.orm import Session

from langgraph.graph import StateGraph
from pydantic import BaseModel, Field

from core.config import get_settings
from core.db.models import AgentMemoryProfile, Session as DbSession
from core.integrations.langchain_provider import get_chat_model
from core.services.memory import (
    get_memory_profile,
    normalize_facts,
    normalize_preferences,
    sync_facts_to_vector_store,
)
from core.runtime.workflow import compact_session_memory

logger = logging.getLogger(__name__)


class MemoryState(TypedDict, total=False):
    session_id: int
    user_message: str
    answer: str
    max_messages: int
    runtime_config: Optional[dict]
    
    # 租户隔离上下文
    workspace_id: int
    user_id: int
    agent_id: int
    
    # 节点输出
    compaction_event: Optional[dict]
    older_turns: Optional[List[dict]]
    extracted_facts: Optional[List[str]]
    extracted_preferences: Optional[Dict[str, str]]


class ExtractedMemory(BaseModel):
    facts: list[str] = Field(default_factory=list, description="值得长期记住的稳定事实")
    preferences: dict[str, str] = Field(default_factory=dict, description="用户稳定偏好 KV")


def _build_graph(db: Session, settings: Any):
    
    def compact_node(state: MemoryState) -> dict:
        """短期记忆压缩节点。"""
        compaction_event = compact_session_memory(
            db,
            state["session_id"],
            state["user_message"],
            state["answer"],
            state["max_messages"],
            state["runtime_config"],
        )
        older_turns = compaction_event.get("older_turns_list", [])
        return {
            "compaction_event": compaction_event,
            "older_turns": older_turns,
        }

    def extract_node(state: MemoryState) -> dict:
        """从被压缩的历史轮次中提取事实与偏好节点。"""
        # 仅当 MEMORY_LONG_TERM_EXTRACT 开启时提取
        if not settings.memory_long_term_extract_enabled:
            return {"extracted_facts": [], "extracted_preferences": {}}

        older_turns = state.get("older_turns")
        # 且触发了压缩时提取（如果没有 older_turns 意为未触发压缩）
        if not older_turns:
            return {"extracted_facts": [], "extracted_preferences": {}}

        try:
            from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
            messages = [
                SystemMessage(content=(
                    "你是一个长期记忆提取助手。请从以下对话历史中提取出值得长期记住的稳定事实（facts）"
                    "和用户的稳定特征偏好（preferences）。\n"
                    "提取原则：\n"
                    "1. 事实应当是关于用户的客观事实或持久信息，例如：用户的姓名、职业、所在地、习惯等。\n"
                    "2. 偏好应当是用户明确表达的喜好、习惯或要求，以键值对（KV）形式存储。键应当简短，值应当是具体偏好，如 {'theme': 'dark', 'language': 'Python'}。\n"
                    "3. 仅提取对话中明确体现的信息，不要猜测或过度外推。"
                ))
            ]
            for turn in older_turns:
                u = turn.get("user") or ""
                a = turn.get("assistant") or ""
                if u:
                    messages.append(HumanMessage(content=u))
                if a:
                    messages.append(AIMessage(content=a))

            # ChatModel 一律走 get_chat_model
            chat = get_chat_model(
                model=settings.memory_summary_model,
                temperature=0.0,
                runtime_config=state.get("runtime_config"),
            )
            # 使用 with_structured_output 提取结构化数据
            structured_chat = chat.with_structured_output(ExtractedMemory, method="function_calling")
            extracted = structured_chat.invoke(messages)
            if extracted:
                return {
                    "extracted_facts": extracted.facts,
                    "extracted_preferences": extracted.preferences,
                }
        except Exception as e:
            # 抽取失败静默跳过，不影响短期压缩
            logger.warning("Failed to extract long-term memory in memory pipeline: %s", e)

        return {"extracted_facts": [], "extracted_preferences": {}}

    def persist_node(state: MemoryState) -> dict:
        """长期记忆持久化与向量同步节点。"""
        extracted_facts = state.get("extracted_facts") or []
        extracted_preferences = state.get("extracted_preferences") or {}

        if not extracted_facts and not extracted_preferences:
            return {}

        try:
            workspace_id = state["workspace_id"]
            user_id = state["user_id"]
            agent_id = state["agent_id"]

            # 获取或创建长期记忆 profile，强制三元组隔离
            profile = get_memory_profile(db, workspace_id=workspace_id, user_id=user_id, agent_id=agent_id)
            if not profile:
                profile = AgentMemoryProfile(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    facts=[],
                    preferences={},
                    enabled=True,
                )
                db.add(profile)

            # 更新事实：自动抽取出的 fact，source 标 "auto"，复用 normalize_facts 去重
            if extracted_facts:
                new_facts_objs = [
                    {
                        "text": fact,
                        "source": "auto",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "score": 1.0
                    }
                    for fact in extracted_facts if fact.strip()
                ]
                existing_facts = profile.facts or []
                profile.facts = normalize_facts(existing_facts + new_facts_objs)

            # 更新偏好
            if extracted_preferences:
                existing_prefs = normalize_preferences(profile.preferences)
                for k, v in extracted_preferences.items():
                    if v is not None:
                        existing_prefs[k] = v
                profile.preferences = normalize_preferences(existing_prefs)

            profile.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(profile)

            # 向量库同步
            if extracted_facts:
                sync_facts_to_vector_store(profile)

        except Exception as e:
            db.rollback()
            logger.warning("Failed to persist long-term memory in persist_node: %s", e)

        return {}

    workflow = StateGraph(MemoryState)
    workflow.add_node("compact", compact_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("persist", persist_node)

    workflow.set_entry_point("compact")
    workflow.add_edge("compact", "extract")
    workflow.add_edge("extract", "persist")
    workflow.set_finish_point("persist")

    return workflow.compile()


def run_memory_pipeline(
    db: Session,
    session_id: int,
    user_message: str,
    answer: str,
    max_messages: int,
    runtime_config: dict | None = None,
) -> dict:
    """
    运行长期记忆管道：压缩 -> 提取 -> 持久化与向量同步。
    任何失败都会降级返回 basic compaction_event，确保绝对高可用。
    """
    session = db.query(DbSession).filter(DbSession.id == session_id).first()
    if not session:
        # 如果 session 找不到，至少回退执行基础压缩
        return compact_session_memory(db, session_id, user_message, answer, max_messages, runtime_config)

    initial_state = {
        "session_id": session_id,
        "user_message": user_message,
        "answer": answer,
        "max_messages": max_messages,
        "runtime_config": runtime_config,
        "workspace_id": session.workspace_id,
        "user_id": session.user_id,
        "agent_id": session.agent_id,
        "compaction_event": None,
        "older_turns": None,
        "extracted_facts": None,
        "extracted_preferences": None,
    }

    try:
        settings = get_settings()
        graph = _build_graph(db, settings)
        final_state = graph.invoke(initial_state)
        # 返回基础压缩事件
        return final_state.get("compaction_event") or {"triggered": False}
    except Exception as e:
        logger.exception("Failed to run memory pipeline, falling back to basic compaction: %s", e)
        return compact_session_memory(db, session_id, user_message, answer, max_messages, runtime_config)
