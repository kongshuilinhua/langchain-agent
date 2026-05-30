from __future__ import annotations

import copy

from sqlalchemy.orm import Session

from core.db.models import (
    Agent,
    AgentKnowledgeBase,
    AgentMemoryProfile,
    AgentSettings,
    AgentTool,
    AgentVersion,
    Feedback,
    KnowledgeBase,
    Message,
    ModelConfig,
    Run,
    RunStep,
    Session as ChatSession,
    SessionMemory,
    Tool,
    UserModelConfig,
    WorkflowDefinition,
)
from core.config import get_settings
from core.services.bootstrap import DEFAULT_WORKFLOW
from core.services.models import model_payload
from core.services.tools import tool_payload
from core.services.user_models import user_model_snapshot


DEFAULT_SUGGESTED_QUESTIONS = [
    "这个智能体能帮我做什么？",
    "请基于知识库回答一个问题。",
]

DEFAULT_MEMORY = {"enabled": False, "strategy": "session_summary", "max_messages": 12}
DEFAULT_RAG = {
    "enabled_by_default": True,
    "top_k": 4,
    "dense_top_k": 12,
    "bm25_top_k": 12,
    "rrf_k": 60,
    "rerank_enabled": True,
    "rerank_top_n": 6,
    "cache_enabled": True,
    "refuse_when_no_evidence": True,
}
DEFAULT_TOOL_POLICY = {"mode": "auto", "allowed_tool_names": []}
LEGACY_TEAM_AGENT_TEXT = {
    "description": (
        "面向团队内部使用的自定义智能体。",
        "用于个人或项目场景的自定义智能体。",
    ),
    "opening_message": (
        "你好，我是你的团队智能体。",
        "你好，我是你的智能体。",
    ),
    "system_prompt": (
        "你是一个谨慎、清晰的团队智能体。优先使用绑定知识库和工具输出回答。",
        "你是一个谨慎、清晰的智能体。优先使用绑定知识库和工具输出回答。",
    ),
}


def agent_summary(agent: Agent) -> dict:
    return {
        "id": agent.id,
        "name": agent.name,
        "avatar": agent.avatar,
        "model_id": agent.model_id,
        "user_model_config_id": agent.user_model_config_id,
        "description": current_agent_text("description", agent.description),
        "opening_message": current_agent_text("opening_message", agent.opening_message),
        "model": agent.model,
        "temperature": agent.temperature,
        "status": agent.status,
        "is_template": agent.is_template,
        "created_by": agent.created_by,
        "published_version_id": agent.published_version_id,
        "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
    }


def get_agent_detail(db: Session, agent: Agent) -> dict:
    kb_ids = [
        row.knowledge_base_id
        for row in db.query(AgentKnowledgeBase).filter(AgentKnowledgeBase.agent_id == agent.id).all()
    ]
    tool_ids = [row.tool_id for row in db.query(AgentTool).filter(AgentTool.agent_id == agent.id).all()]
    tools = db.query(Tool).filter(Tool.id.in_(tool_ids)).all() if tool_ids else []
    workflow = db.query(WorkflowDefinition).filter(WorkflowDefinition.agent_id == agent.id).first()
    settings = ensure_agent_settings(db, agent.id)
    model_config = db.get(ModelConfig, agent.model_id) if agent.model_id else None
    user_model_config = db.get(UserModelConfig, agent.user_model_config_id) if agent.user_model_config_id else None
    return {
        **agent_summary(agent),
        "user_model_config_id": agent.user_model_config_id,
        "system_prompt": current_agent_text("system_prompt", agent.system_prompt),
        "knowledge_base_ids": kb_ids,
        "tools": [tool_payload(tool) for tool in tools],
        "workflow": workflow.nodes if workflow else DEFAULT_WORKFLOW,
        "model_config": model_payload(model_config) if model_config else None,
        "user_model_config": user_model_snapshot(user_model_config),
        "suggested_questions": settings.suggested_questions or [],
        "variables": settings.variables or [],
        "memory": normalize_memory(settings.memory),
        "rag": normalize_rag(settings.rag),
        "tool_policy": normalize_tool_policy(settings.tool_policy),
    }


def create_agent(db: Session, *, workspace_id: int, user_id: int, payload: dict) -> Agent:
    agent = Agent(
        workspace_id=workspace_id,
        model_id=payload.get("model_id"),
        user_model_config_id=payload.get("user_model_config_id"),
        name=payload["name"],
        avatar=payload.get("avatar") or "AI",
        description=payload.get("description") or "",
        opening_message=payload.get("opening_message") or "",
        system_prompt=payload.get("system_prompt") or "",
        model=payload.get("model") or "qwen-plus",
        temperature=payload.get("temperature", 0.4),
        created_by=user_id,
    )
    db.add(agent)
    db.flush()
    db.add(WorkflowDefinition(agent_id=agent.id, nodes=DEFAULT_WORKFLOW))
    db.add(
        AgentSettings(
            agent_id=agent.id,
            suggested_questions=normalize_questions(payload.get("suggested_questions")),
            variables=normalize_variables(payload.get("variables")),
            memory=normalize_memory(payload.get("memory")),
            rag=normalize_rag(payload.get("rag")),
            tool_policy=normalize_tool_policy(payload.get("tool_policy")),
        )
    )
    _replace_agent_knowledge(db, agent.id, payload.get("knowledge_base_ids") or [])
    _replace_agent_tools(db, agent.id, payload.get("tool_ids") or [])
    db.commit()
    db.refresh(agent)
    return agent


def update_agent(db: Session, agent: Agent, payload: dict) -> Agent:
    for key in ["model_id", "user_model_config_id"]:
        if key in payload:
            setattr(agent, key, payload[key])
    for key in ["name", "avatar", "description", "opening_message", "system_prompt", "model", "temperature"]:
        if key in payload and payload[key] is not None:
            setattr(agent, key, payload[key])
    if "knowledge_base_ids" in payload:
        _replace_agent_knowledge(db, agent.id, payload["knowledge_base_ids"] or [])
    if "tool_ids" in payload:
        _replace_agent_tools(db, agent.id, payload["tool_ids"] or [])
    if any(key in payload for key in ["suggested_questions", "variables", "memory", "rag", "tool_policy"]):
        settings = ensure_agent_settings(db, agent.id)
        if "suggested_questions" in payload:
            settings.suggested_questions = normalize_questions(payload["suggested_questions"])
        if "variables" in payload:
            settings.variables = normalize_variables(payload["variables"])
        if "memory" in payload:
            settings.memory = normalize_memory(payload["memory"])
        if "rag" in payload:
            settings.rag = normalize_rag(payload["rag"])
        if "tool_policy" in payload:
            settings.tool_policy = normalize_tool_policy(payload["tool_policy"])
    db.commit()
    db.refresh(agent)
    return agent


def publish_agent(db: Session, agent: Agent, user_id: int, *, require_review: bool = False) -> AgentVersion:
    latest = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).order_by(AgentVersion.version.desc()).first()
    version_number = (latest.version + 1) if latest else 1
    snapshot = get_agent_detail(db, agent)
    version = AgentVersion(agent_id=agent.id, version=version_number, snapshot=snapshot, created_by=user_id)
    db.add(version)
    db.flush()
    if require_review:
        agent.status = "pending_review"
    else:
        agent.status = "published"
        agent.published_version_id = version.id
    db.commit()
    db.refresh(version)
    return version


def ensure_template_agents_published(db: Session, workspace_id: int) -> None:
    templates = (
        db.query(Agent)
        .filter(Agent.workspace_id == workspace_id, Agent.is_template.is_(True))
        .all()
    )
    changed = False
    for agent in templates:
        if agent.status == "published" and agent.published_version_id:
            continue
        agent.status = "published"
        version = latest_agent_version(db, agent)
        if not version:
            version = AgentVersion(
                agent_id=agent.id,
                version=1,
                snapshot=get_agent_detail(db, agent),
                created_by=agent.created_by,
            )
            db.add(version)
            db.flush()
        agent.published_version_id = version.id
        changed = True
    if changed:
        db.commit()


def latest_agent_version(db: Session, agent: Agent) -> AgentVersion | None:
    return db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).order_by(AgentVersion.version.desc()).first()


def approve_agent(db: Session, agent: Agent, reviewer_id: int) -> AgentVersion:
    version = latest_agent_version(db, agent)
    if not version:
        version = publish_agent(db, agent, reviewer_id, require_review=False)
    agent.status = "published"
    agent.published_version_id = version.id
    db.commit()
    db.refresh(version)
    return version


def reject_agent(db: Session, agent: Agent) -> Agent:
    agent.status = "rejected"
    db.commit()
    db.refresh(agent)
    return agent


def delete_agent(db: Session, agent: Agent) -> None:
    if agent.is_template:
        raise ValueError("Template agents cannot be deleted")

    session_ids = [
        row.id
        for row in db.query(ChatSession.id).filter(ChatSession.agent_id == agent.id).all()
    ]
    message_ids = []
    if session_ids:
        message_ids = [
            row.id
            for row in db.query(Message.id).filter(Message.session_id.in_(session_ids)).all()
        ]
    run_ids = [
        row.id
        for row in db.query(Run.id).filter(Run.agent_id == agent.id).all()
    ]

    if message_ids:
        db.query(Feedback).filter(Feedback.message_id.in_(message_ids)).delete(synchronize_session=False)
    if run_ids:
        db.query(RunStep).filter(RunStep.run_id.in_(run_ids)).delete(synchronize_session=False)
    if session_ids:
        db.query(SessionMemory).filter(SessionMemory.session_id.in_(session_ids)).delete(synchronize_session=False)
        db.query(Message).filter(Message.session_id.in_(session_ids)).delete(synchronize_session=False)
    db.query(Run).filter(Run.agent_id == agent.id).delete(synchronize_session=False)
    db.query(ChatSession).filter(ChatSession.agent_id == agent.id).delete(synchronize_session=False)
    db.query(AgentKnowledgeBase).filter(AgentKnowledgeBase.agent_id == agent.id).delete(synchronize_session=False)
    db.query(AgentMemoryProfile).filter(AgentMemoryProfile.agent_id == agent.id).delete(synchronize_session=False)
    db.query(AgentTool).filter(AgentTool.agent_id == agent.id).delete(synchronize_session=False)
    db.query(AgentSettings).filter(AgentSettings.agent_id == agent.id).delete(synchronize_session=False)
    db.query(WorkflowDefinition).filter(WorkflowDefinition.agent_id == agent.id).delete(synchronize_session=False)
    db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).delete(synchronize_session=False)
    db.delete(agent)
    db.commit()


def market_agent_summary(agent: Agent, version: AgentVersion | None = None) -> dict:
    snapshot = normalize_snapshot_text((version.snapshot if version else None) or {})
    return {
        "id": agent.id,
        "name": snapshot.get("name") or agent.name,
        "avatar": snapshot.get("avatar") or agent.avatar,
        "description": snapshot.get("description") or agent.description,
        "status": agent.status,
        "version": version.version if version else None,
        "published_version_id": agent.published_version_id,
        "created_by": agent.created_by,
        "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
    }


def copy_agent_from_market(db: Session, *, source: Agent, user_id: int, workspace_id: int) -> Agent:
    version = db.get(AgentVersion, source.published_version_id) if source.published_version_id else None
    if not version:
        raise ValueError("Agent has no approved version")
    snapshot = normalize_snapshot_text(version.snapshot or {})
    copied = create_agent(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
        payload={
            "name": f"{snapshot.get('name') or source.name} 副本",
            "avatar": snapshot.get("avatar") or source.avatar,
            "description": snapshot.get("description") or source.description,
            "opening_message": snapshot.get("opening_message") or source.opening_message,
            "system_prompt": snapshot.get("system_prompt") or source.system_prompt,
            "model": snapshot.get("model") or source.model,
            "model_id": snapshot.get("model_id") or source.model_id,
            "user_model_config_id": snapshot.get("user_model_config_id") or source.user_model_config_id,
            "temperature": snapshot.get("temperature", source.temperature),
            "knowledge_base_ids": snapshot.get("knowledge_base_ids") or [],
            "tool_ids": [tool.get("id") for tool in snapshot.get("tools", []) if tool.get("id")],
            "suggested_questions": snapshot.get("suggested_questions") or [],
            "variables": snapshot.get("variables") or [],
            "memory": snapshot.get("memory") or DEFAULT_MEMORY,
            "rag": snapshot.get("rag") or DEFAULT_RAG,
            "tool_policy": snapshot.get("tool_policy") or DEFAULT_TOOL_POLICY,
        },
    )
    workflow = db.query(WorkflowDefinition).filter(WorkflowDefinition.agent_id == copied.id).first()
    if workflow:
        workflow.nodes = snapshot.get("workflow") or DEFAULT_WORKFLOW
        db.commit()
    db.refresh(copied)
    return copied


def current_agent_text(field: str, value: str) -> str:
    old_value, new_value = LEGACY_TEAM_AGENT_TEXT.get(field, ("", ""))
    return new_value if value == old_value else value


def normalize_snapshot_text(snapshot: dict) -> dict:
    data = copy.deepcopy(snapshot)
    for field in ["description", "opening_message", "system_prompt"]:
        if field in data:
            data[field] = current_agent_text(field, data[field])
    return data


def ensure_agent_settings(db: Session, agent_id: int) -> AgentSettings:
    settings = db.query(AgentSettings).filter(AgentSettings.agent_id == agent_id).first()
    if settings:
        return settings
    settings = AgentSettings(
        agent_id=agent_id,
        suggested_questions=DEFAULT_SUGGESTED_QUESTIONS,
        variables=[],
        memory=DEFAULT_MEMORY,
        rag=DEFAULT_RAG,
        tool_policy=DEFAULT_TOOL_POLICY,
    )
    db.add(settings)
    db.flush()
    return settings


def normalize_questions(value) -> list[str]:
    if not value:
        return []
    return [str(item).strip() for item in value if str(item).strip()][:8]


def normalize_variables(value) -> list[dict]:
    if not value:
        return []
    allowed_types = {"string", "number", "boolean"}
    normalized = []
    for item in value:
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        var_type = data.get("type") if data.get("type") in allowed_types else "string"
        key = str(data.get("key", "")).strip()
        label = str(data.get("label", "")).strip() or key
        if not key:
            continue
        normalized.append(
            {
                "key": key,
                "label": label,
                "type": var_type,
                "required": bool(data.get("required", False)),
                "default_value": data.get("default_value"),
            }
        )
    return normalized[:20]


def normalize_memory(value) -> dict:
    data = value.model_dump() if hasattr(value, "model_dump") else dict(value or {})
    strategy = data.get("strategy") if data.get("strategy") == "session_summary" else "session_summary"
    max_messages = int(data.get("max_messages") or 12)
    return {"enabled": bool(data.get("enabled", False)), "strategy": strategy, "max_messages": max(1, min(max_messages, 100))}


def normalize_rag(value) -> dict:
    settings = get_settings()
    data = value.model_dump() if hasattr(value, "model_dump") else dict(value or {})
    top_k = int(data.get("top_k") or settings.rag_top_k)
    dense_top_k = int(data.get("dense_top_k") or settings.rag_dense_top_k)
    bm25_top_k = int(data.get("bm25_top_k") or settings.rag_bm25_top_k)
    rrf_k = int(data.get("rrf_k") or settings.rag_rrf_k)
    rerank_top_n = int(data.get("rerank_top_n") or settings.rag_rerank_top_n)
    return {
        "enabled_by_default": bool(data.get("enabled_by_default", True)),
        "top_k": max(1, min(top_k, 20)),
        "dense_top_k": max(1, min(dense_top_k, 50)),
        "bm25_top_k": max(1, min(bm25_top_k, 50)),
        "rrf_k": max(1, min(rrf_k, 200)),
        "rerank_enabled": bool(data.get("rerank_enabled", settings.rag_rerank_enabled)),
        "rerank_top_n": max(1, min(rerank_top_n, 20)),
        "cache_enabled": bool(data.get("cache_enabled", settings.rag_cache_enabled)),
        "refuse_when_no_evidence": bool(data.get("refuse_when_no_evidence", settings.rag_refuse_when_no_evidence)),
    }


def normalize_tool_policy(value) -> dict:
    data = value.model_dump() if hasattr(value, "model_dump") else dict(value or {})
    mode = data.get("mode") if data.get("mode") == "auto" else "auto"
    names = [str(item).strip() for item in data.get("allowed_tool_names", []) if str(item).strip()]
    return {"mode": mode, "allowed_tool_names": names[:50]}


def _replace_agent_knowledge(db: Session, agent_id: int, knowledge_base_ids: list[int]) -> None:
    db.query(AgentKnowledgeBase).filter(AgentKnowledgeBase.agent_id == agent_id).delete()
    for kb_id in knowledge_base_ids:
        db.add(AgentKnowledgeBase(agent_id=agent_id, knowledge_base_id=kb_id))


def _replace_agent_tools(db: Session, agent_id: int, tool_ids: list[int]) -> None:
    db.query(AgentTool).filter(AgentTool.agent_id == agent_id).delete()
    for tool_id in tool_ids:
        db.add(AgentTool(agent_id=agent_id, tool_id=tool_id))


def workspace_kb_exists(db: Session, workspace_id: int, kb_id: int) -> bool:
    return db.query(KnowledgeBase).filter(KnowledgeBase.workspace_id == workspace_id, KnowledgeBase.id == kb_id).first() is not None
