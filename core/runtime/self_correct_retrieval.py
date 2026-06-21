from __future__ import annotations

import json
from typing import TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from core.config import get_settings
from core.integrations.langchain_provider import get_chat_model
from core.services import rag
from core.services.rag import RagResult


class RetrievalGrade(BaseModel):
    sufficient: bool = Field(description="检索结果是否足以回答当前查询")


class QueryRewrite(BaseModel):
    rewritten_query: str = Field(description="更适合知识库检索的自包含查询")


class RetrievalState(TypedDict, total=False):
    query: str
    original_query: str
    kb_ids: list[int]
    workspace_id: int
    runtime_config: dict | None
    sources: list[dict]
    status: dict
    rounds: int
    sufficient: bool
    rewritten: bool
    grade_error: bool


def _source_context(sources: list[dict]) -> str:
    """压缩来源供评分/改写使用，限制提示词体积。"""
    items = []
    for source in sources[:8]:
        text = source.get("content") or source.get("snippet") or ""
        items.append(
            {
                "title": source.get("title") or source.get("source_id") or "knowledge",
                "text": str(text)[:1200],
            }
        )
    return json.dumps(items, ensure_ascii=False)


def _build_graph(db, *, config: dict, max_rounds: int):
    def retrieve_node(state: RetrievalState) -> dict:
        result = rag.retrieve(
            db,
            workspace_id=state["workspace_id"],
            knowledge_base_ids=state["kb_ids"],
            query=state["query"],
            config=config,
            runtime_config=state.get("runtime_config"),
        )
        return {
            "sources": result.sources,
            "status": result.status,
            "rounds": int(state.get("rounds", 0)) + 1,
        }

    def grade_node(state: RetrievalState) -> dict:
        try:
            chat = get_chat_model(temperature=0.0, runtime_config=state.get("runtime_config"))
            structured = chat.with_structured_output(RetrievalGrade, method="function_calling")
            result = structured.invoke(
                [
                    {
                        "role": "system",
                        "content": (
                            "判断检索片段是否包含足以回答查询的证据。只判断证据充分性；"
                            "不要补充片段之外的事实。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"查询：{state['query']}\n检索片段：{_source_context(state.get('sources', []))}",
                    },
                ]
            )
            return {"sufficient": result.sufficient, "grade_error": False}
        except Exception:
            # 评分不可用时立即接受当前结果，避免评分故障引发循环或阻断原检索。
            return {"sufficient": True, "grade_error": True}

    def rewrite_node(state: RetrievalState) -> dict:
        chat = get_chat_model(temperature=0.0, runtime_config=state.get("runtime_config"))
        structured = chat.with_structured_output(QueryRewrite, method="function_calling")
        result = structured.invoke(
            [
                {
                    "role": "system",
                    "content": "把查询改写成自包含、关键词明确且更适合知识库检索的表述，不要回答问题。",
                },
                {
                    "role": "user",
                    "content": f"原查询：{state['query']}\n未充分命中的片段：{_source_context(state.get('sources', []))}",
                },
            ]
        )
        rewritten_query = result.rewritten_query.strip()
        if not rewritten_query:
            raise ValueError("query rewrite returned empty text")
        return {"query": rewritten_query, "rewritten": rewritten_query != state["original_query"]}

    def after_grade(state: RetrievalState) -> str:
        if state.get("sufficient", True) or int(state.get("rounds", 0)) >= max_rounds:
            return "end"
        return "rewrite"

    graph = StateGraph(RetrievalState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("grade", grade_node)
    graph.add_node("rewrite", rewrite_node)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges("grade", after_grade, {"end": END, "rewrite": "rewrite"})
    graph.add_edge("rewrite", "retrieve")
    return graph.compile()


def self_correct_retrieve(
    db,
    *,
    workspace_id: int,
    knowledge_base_ids: list[int],
    query: str,
    config: dict,
    runtime_config: dict | None = None,
) -> RagResult:
    """运行 CRAG-lite；任何内部异常均回退到原生单趟检索。"""
    try:
        configured_rounds = config.get("self_correct_max_rounds")
        max_rounds = max(
            1,
            int(
                configured_rounds
                if configured_rounds is not None
                else get_settings().rag_self_correct_max_rounds
            ),
        )
        graph = _build_graph(db, config=config, max_rounds=max_rounds)
        final_state = graph.invoke(
            {
                "query": query,
                "original_query": query,
                "kb_ids": knowledge_base_ids,
                "workspace_id": workspace_id,
                "runtime_config": runtime_config,
                "sources": [],
                "status": {},
                "rounds": 0,
                "sufficient": False,
                "rewritten": False,
                "grade_error": False,
            }
        )
        trace = {
            "enabled": True,
            "rounds": int(final_state.get("rounds", 0)),
            "rewritten": bool(final_state.get("rewritten", False)),
            "original_query": query,
            "final_query": final_state.get("query") or query,
            "grade_error": bool(final_state.get("grade_error", False)),
        }
        status = {**(final_state.get("status") or {}), "self_correct": trace}
        return RagResult(final_state.get("sources") or [], status)
    except Exception:
        return rag.retrieve(
            db,
            workspace_id=workspace_id,
            knowledge_base_ids=knowledge_base_ids,
            query=query,
            config=config,
            runtime_config=runtime_config,
        )
