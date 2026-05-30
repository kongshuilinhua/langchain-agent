from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import get_settings
from core.db.models import (
    Agent,
    AgentKnowledgeBase,
    AgentTool,
    KnowledgeBase,
    ModelConfig,
    Tool,
    User,
    WorkflowDefinition,
    Workspace,
    WorkspaceMember,
)
from core.security.auth import hash_password
from core.services.tools import BUILTIN_TOOLS


DEFAULT_WORKFLOW = [
    {"id": "start", "type": "Start", "name": "接收用户输入", "config": {}},
    {"id": "knowledge", "type": "Knowledge", "name": "检索绑定知识库", "config": {"top_k": 4}},
    {"id": "tool", "type": "Tool", "name": "调用绑定工具", "config": {"tools": []}},
    {"id": "llm", "type": "LLM", "name": "生成候选回答", "config": {}},
    {"id": "answer", "type": "Answer", "name": "输出最终回答", "config": {}},
]


def ensure_builtin_tools(db: Session) -> None:
    # Clean up legacy builtin tools whose names are no longer in the registry.
    registry_names = set(BUILTIN_TOOLS.keys())
    legacy_ids = [
        row.id for row in db.query(Tool.id).filter(
            Tool.type == "builtin",
            Tool.name.notin_(registry_names),
        ).all()
    ]
    if legacy_ids:
        db.query(AgentTool).filter(AgentTool.tool_id.in_(legacy_ids)).delete(synchronize_session=False)
        db.query(Tool).filter(Tool.id.in_(legacy_ids)).delete(synchronize_session=False)

    # Upsert builtin tools from registry.
    for name, impl in BUILTIN_TOOLS.items():
        tool = db.query(Tool).filter(Tool.name == name, Tool.type == "builtin").first()
        if tool:
            tool.description = impl["description"]
            tool.label = name
            tool.enabled = True
            continue
        db.add(Tool(name=name, label=name, description=impl["description"], schema={}, type="builtin", enabled=True))

    # Upsert builtin_search adapter.
    search_tool = db.query(Tool).filter(Tool.name == "web_search").first()
    if search_tool:
        search_tool.type = "builtin_search"
        search_tool.label = "Web Search"
        search_tool.description = "Built-in web search adapter for Agent tools"
    else:
        db.add(Tool(name="web_search", label="Web Search", description="Built-in web search adapter for Agent tools", schema={}, type="builtin_search"))

    db.commit()


def ensure_default_models(db: Session) -> None:
    settings = get_settings()
    defaults = [
        {
            "model_name": settings.openai_model,
            "display_name": settings.openai_model,
            "provider": "openai-compatible",
            "supports_text": True,
            "supports_image": False,
            "supports_document": True,
            "supports_reasoning": True,
            "reasoning_type": "prompt",
            "reasoning_label": "提示词增强",
            "max_context": 131072,
            "default_temperature": 0.4,
        },
        {
            "model_name": "qwen-vl-plus",
            "display_name": "Qwen VL Plus",
            "provider": "openai-compatible",
            "supports_text": True,
            "supports_image": True,
            "supports_document": True,
            "supports_reasoning": True,
            "reasoning_type": "prompt",
            "reasoning_label": "提示词增强",
            "max_context": 32768,
            "default_temperature": 0.4,
        },
    ]
    changed = False
    for item in defaults:
        if db.query(ModelConfig).filter(ModelConfig.model_name == item["model_name"]).first():
            continue
        db.add(ModelConfig(enabled=True, **item))
        changed = True
    if changed:
        db.commit()


def ensure_template_agent(db: Session, owner: User, workspace: Workspace) -> Agent:
    existing = db.query(Agent).filter(Agent.workspace_id == workspace.id, Agent.is_template.is_(True)).first()
    if existing:
        return existing
    kb = KnowledgeBase(
        workspace_id=workspace.id,
        name="扫地机器人客服知识库",
        description="内置模板知识库，演示智能硬件客服 RAG 场景。",
        created_by=owner.id,
    )
    db.add(kb)
    db.flush()
    agent = Agent(
        workspace_id=workspace.id,
        name="扫地机器人客服",
        avatar="SR",
        description="面向扫地机器人售前、故障排查和维护保养的示例智能体。",
        opening_message="你好，我可以帮你排查扫地机器人问题、解释维护建议，也可以演示知识库引用。",
        system_prompt="你是一个谨慎的中文智能硬件客服智能体。优先基于绑定知识库回答，资料不足时明确说明。",
        model=get_settings().openai_model,
        temperature=0.3,
        is_template=True,
        created_by=owner.id,
    )
    db.add(agent)
    db.flush()
    db.add(AgentKnowledgeBase(agent_id=agent.id, knowledge_base_id=kb.id))
    db.add(WorkflowDefinition(agent_id=agent.id, nodes=DEFAULT_WORKFLOW))
    db.commit()
    return agent


def create_first_user_workspace(db: Session, *, email: str, name: str, password: str) -> tuple[User, Workspace]:
    user = User(email=email.lower(), name=name, password_hash=hash_password(password))
    workspace = Workspace(name=f"{name} 的工作台", slug="default")
    db.add_all([user, workspace])
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="admin"))
    db.commit()
    ensure_default_models(db)
    ensure_builtin_tools(db)
    ensure_template_agent(db, user, workspace)
    return user, workspace


def create_default_workspace_user(db: Session, *, email: str, name: str, password: str) -> tuple[User, Workspace]:
    workspace = db.query(Workspace).filter(Workspace.slug == "default").first()
    if not workspace:
        workspace = db.query(Workspace).order_by(Workspace.id.asc()).first()
    if not workspace:
        return create_first_user_workspace(db, email=email, name=name, password=password)
    user = User(email=email.lower(), name=name, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="user"))
    db.commit()
    return user, workspace


def has_any_user(db: Session) -> bool:
    return db.query(User).first() is not None
