from __future__ import annotations

import json
import logging
import re
import secrets
import time
from collections.abc import Iterable

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.deps import get_current_membership, get_current_user, require_manager
from api.schemas import (
    AgentCreateRequest,
    AgentUpdateRequest,
    ChatRequest,
    FeedbackRequest,
    InviteAcceptRequest,
    InviteCreateRequest,
    KnowledgeBaseCreateRequest,
    KnowledgeDocumentCreateRequest,
    LoginRequest,
    MemoryProfileUpdateRequest,
    ModelConfigRequest,
    ModelConfigUpdateRequest,
    PromptTemplateCopyBuiltinRequest,
    PromptTemplateRequest,
    PromptTemplateUpdateRequest,
    RegisterRequest,
    SessionUpdateRequest,
    ToolRequest,
    ToolTestRequest,
    ToolUpdateRequest,
    UploadCreateRequest,
    UserProfileUpdateRequest,
    UserModelCapabilityTestRequest,
    UserModelConfigRequest,
    UserModelConfigUpdateRequest,
    WorkflowUpdateRequest,
)
from core.config import get_settings
from core.db.models import (
    Agent,
    AgentVersion,
    Feedback,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    Message,
    ModelConfig,
    Run,
    RunStep,
    Session as ChatSession,
    SessionMemory,
    Tool,
    User,
    UserModelConfig,
    WorkflowDefinition,
    WorkspaceInvite,
    WorkspaceMember,
)
from core.db.session import engine, get_db, init_db
from core.integrations.llm import DASHSCOPE_COMPATIBLE_BASE, OPENAI_COMPATIBLE_DEFAULT_BASE, OpenAICompatibleProvider
from core.integrations.vector_store import vector_store
from core.runtime.workflow import WorkflowRunner, default_workflow
from core.security.auth import create_access_token, hash_password, verify_password
from core.security.api_keys import secret_storage_ready
from core.security.permissions import can_manage, normalize_role
from core.services.agents import (
    agent_summary,
    approve_agent,
    copy_agent_from_market,
    create_agent,
    delete_agent as delete_agent_service,
    ensure_template_agents_published,
    get_agent_detail,
    market_agent_summary,
    publish_agent,
    reject_agent,
    update_agent,
)
from core.services.bootstrap import (
    create_default_workspace_user,
    create_first_user_workspace,
    ensure_builtin_tools,
    ensure_default_models,
    has_any_user,
)
from core.services.knowledge import (
    KnowledgeDocumentError,
    add_document,
    create_knowledge_base,
    delete_document,
    delete_knowledge_base,
    document_payload,
    knowledge_base_summary,
    list_document_chunks,
    reindex_knowledge_base,
    split_by_hierarchy,
    split_parent_child,
    index_document,
)
from core.services.rag_cache import redis_store
from core.services.memory import (
    delete_memory_profile,
    get_memory_profile,
    memory_profile_payload,
    upsert_memory_profile,
)
from core.services.models import create_model_config, delete_model_config, model_payload, update_model_config
from core.services.prompt_templates import (
    copy_builtin_prompt_template,
    create_prompt_template,
    delete_prompt_template,
    get_owned_prompt_template,
    list_prompt_templates,
    prompt_template_payload,
    update_prompt_template,
)
from core.services.tools import (
    create_tool,
    delete_tool,
    get_accessible_tool,
    list_available_tools,
    test_tool,
    tool_payload,
    update_tool,
    validate_tool_ids,
)
from core.services.uploads import create_upload, upload_payload
from core.services.user_models import (
    create_user_model_config,
    delete_user_model_config,
    get_owned_user_model,
    list_user_model_configs,
    test_user_model_config,
    test_user_model_payload,
    update_user_model_config,
    user_model_payload,
)
from core.services.web_search import search_web


PUBLIC_CHAT_ERRORS = (
    "Selected model does not support document input",
    "Upload not found or not accessible",
    "Stored API key is invalid",
    "Secure API key encryption is not configured",
    "当前智能体还没有发布版本",
    "发布版本不存在",
    "mode must be draft or published",
)


settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version)
logger = logging.getLogger(__name__)
startup_error: str | None = None
_health_probe_cache: dict[str, tuple[float, dict]] = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["http://127.0.0.1:5174", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    global startup_error
    try:
        init_db()
        startup_error = None
    except Exception as exc:
        startup_error = str(exc)[:500]
        logger.exception("Database initialization failed; API started in degraded mode")


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def safe_stream_error(exc: Exception) -> dict:
    message = str(exc)
    if any(public_error in message for public_error in PUBLIC_CHAT_ERRORS):
        return {"message": message, "error_code": _error_code(message)}
    return {
        "message": "智能体运行失败，请检查模型、知识库或附件配置后重试。",
        "error_code": _error_code(message),
    }


def _error_code(message: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", message.lower()).strip("_")
    if "model_call_failed" in normalized or "gateway" in normalized:
        return "model_provider_error"
    if "model" in normalized and "image" in normalized:
        return "model_capability_error"
    if "model" in normalized and "document" in normalized:
        return "model_capability_error"
    if "upload" in normalized:
        return "attachment_error"
    if "publish" in normalized or "发布" in message:
        return "agent_version_error"
    if "api_key" in normalized or "secret" in normalized:
        return "secret_config_error"
    return "agent_runtime_error"


@app.get("/api/health")
def health():
    provider = OpenAICompatibleProvider()
    chat_api_key = provider._api_key(settings, purpose="chat")
    embedding_api_key = provider._api_key(settings, purpose="embedding")
    model_mock = settings.mock_llm
    model_base = settings.openai_api_base
    if settings.deepseek_api_key and ((settings.openai_api_base or "").rstrip("/") == settings.deepseek_api_base.rstrip("/") or settings.openai_model == settings.deepseek_model):
        model_base = settings.deepseek_api_base
    elif settings.dashscope_api_key and not settings.openai_api_key and model_base == OPENAI_COMPATIBLE_DEFAULT_BASE:
        model_base = DASHSCOPE_COMPATIBLE_BASE
    embedding_base = provider._api_base(settings, purpose="embedding")
    embedding_mock = settings.mock_llm
    embedding_model = (settings.openai_embedding_model or "").strip()
    issues = []
    database_status = {"configured": bool(settings.database_url), "available": False, "error": None}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database_status["available"] = True
    except Exception as exc:
        database_status["error"] = str(exc)[:240]
        issues.append("Database is configured but not reachable.")
    if not secret_storage_ready():
        issues.append("API_KEY_ENCRYPTION_KEY or a non-default JWT_SECRET is required before storing user model keys or tool secrets.")
    if startup_error:
        issues.append("Database initialization failed during startup.")
    redis_status = redis_store.status()
    vector_status = vector_store.status()
    model_probe = _model_probe("chat", enabled=bool(settings.health_model_probe_enabled and not model_mock))
    embedding_probe = _model_probe("embedding", enabled=bool(settings.health_model_probe_enabled and not embedding_mock and embedding_model))
    if model_mock:
        issues.append("Chat model is running in mock mode because LINGSHU_MOCK_LLM is true.")
    elif not chat_api_key:
        issues.append("Chat model API key is not configured.")
    elif not model_probe["ok"]:
        issues.append("Chat model gateway probe failed.")
    if embedding_mock:
        issues.append("Embedding is running in mock mode because LINGSHU_MOCK_LLM is true.")
    elif not embedding_model or not embedding_api_key:
        issues.append("Embedding is unavailable for real RAG because OPENAI_EMBEDDING_MODEL and a provider API key are required.")
    elif not embedding_probe["ok"]:
        issues.append("Embedding gateway probe failed.")
    if redis_status["required"] and not redis_status["available"]:
        issues.append("Redis is configured for RAG cache/job state but is not reachable.")
    if vector_status["fallback"]:
        issues.append("Milvus is configured but unavailable; vector operations are using the in-memory fallback.")
    return {
        "status": "degraded" if issues else "ok",
        "version": app.version,
        "issues": issues,
        "dependencies": {
            "database": database_status,
            "startup": {"ok": startup_error is None, "error": startup_error},
            "cors": {"origins": settings.cors_origin_list},
            "redis": redis_status,
            "vector_store": vector_status,
            "model": {
                "provider": "openai-compatible",
                "model": settings.deepseek_model if model_base.rstrip("/") == settings.deepseek_api_base.rstrip("/") else settings.openai_model,
                "base_url": model_base,
                "mock": model_mock,
                "configured": bool(chat_api_key),
                "available": bool((not model_mock) and bool(chat_api_key)),
                "probe": model_probe,
            },
            "embedding": {
                "provider": "openai-compatible",
                "model": embedding_model,
                "base_url": embedding_base,
                "mock": embedding_mock,
                "configured": bool(embedding_model and embedding_api_key),
                "available": bool(embedding_model and embedding_api_key and not embedding_mock and vector_status["available"]),
                "reason": None if bool(embedding_model and embedding_api_key and not embedding_mock and vector_status["available"]) else _runtime_unavailable_reason(embedding_probe, vector_status),
                "probe": embedding_probe,
            },
            "web_search": {
                "provider": settings.web_search_provider,
                "enabled": settings.web_search_enabled,
                "configured": settings.web_search_enabled and settings.web_search_provider == "duckduckgo_html",
                "requires_api_key": False,
                "top_k": settings.web_search_top_k,
            },
            "secret_storage": {
                "configured": secret_storage_ready(),
            },
        },
    }


def _model_probe(purpose: str, *, enabled: bool) -> dict:
    if not enabled:
        return {"enabled": False, "ok": False, "error": None, "cached": False}
    now = time.monotonic()
    cached = _health_probe_cache.get(purpose)
    if cached and now - cached[0] < 300:
        return {**cached[1], "cached": True}
    provider = OpenAICompatibleProvider()
    try:
        if purpose == "chat":
            settings_obj = get_settings()
            use_deepseek = bool(
                settings_obj.deepseek_api_key
                and (
                    (settings_obj.openai_api_base or "").rstrip("/") == settings_obj.deepseek_api_base.rstrip("/")
                    or settings_obj.openai_model == settings_obj.deepseek_model
                )
            )
            model = settings_obj.deepseek_model if use_deepseek else settings_obj.openai_model
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "health"}],
                "temperature": 0,
                "stream": False,
            }
            provider._post_json(
                provider._api_base(settings_obj, purpose="chat").rstrip("/") + "/chat/completions",
                payload,
                provider._api_key(settings_obj, purpose="chat") or "",
                timeout_seconds=8,
            )
        elif purpose == "embedding":
            settings_obj = get_settings()
            provider._post_json(
                provider._api_base(settings_obj, purpose="embedding").rstrip("/") + "/embeddings",
                {"model": settings_obj.openai_embedding_model, "input": "health"},
                provider._api_key(settings_obj, purpose="embedding") or "",
                timeout_seconds=8,
            )
        else:
            raise ValueError("Unsupported health probe")
        result = {"enabled": True, "ok": True, "error": None, "cached": False}
    except Exception as exc:
        result = {"enabled": True, "ok": False, "error": _sanitize_public_error(str(exc)), "cached": False}
    _health_probe_cache[purpose] = (now, result)
    return result


def _runtime_unavailable_reason(probe: dict, vector_status: dict) -> str:
    if not vector_status.get("available"):
        return "vector_store_unavailable"
    if probe.get("enabled") and not probe.get("ok"):
        return "provider_probe_failed"
    return "mock_or_vector_unavailable"


def _sanitize_public_error(message: str) -> str:
    cleaned = re.sub(r"(?i)(sk-[A-Za-z0-9_-]+|api[_-]?key\s*[:=]\s*\S+|secret\s*[:=]\s*\S+)", "[secret]", str(message))
    return cleaned.replace("\n", " ").replace("\r", " ").strip()[:500]


@app.get("/api/search/test")
def test_web_search(q: str = Query(min_length=1, max_length=300), membership: WorkspaceMember = Depends(get_current_membership)):
    try:
        return {"ok": True, **search_web(q)}
    except ValueError as exc:
        return {"ok": False, "query": q, "provider": settings.web_search_provider, "items": [], "error_code": str(exc)}


@app.post("/api/auth/register")
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == request.email.lower()).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    invite = None
    if request.invite_token:
        invite = (
            db.query(WorkspaceInvite)
            .filter(
                WorkspaceInvite.token == request.invite_token,
                WorkspaceInvite.accepted_at.is_(None),
                WorkspaceInvite.email == request.email.lower(),
            )
            .first()
        )
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found")
    if invite:
        user = User(email=request.email.lower(), name=request.name, password_hash=hash_password(request.password))
        db.add(user)
        db.flush()
        db.add(WorkspaceMember(workspace_id=invite.workspace_id, user_id=user.id, role=normalize_role(invite.role)))
        invite.accepted_at = __import__("datetime").datetime.utcnow()
        db.commit()
        workspace = invite_workspace(db, invite.workspace_id)
        role = normalize_role(invite.role)
    elif has_any_user(db):
        user, workspace = create_default_workspace_user(db, email=request.email, name=request.name, password=request.password)
        role = "user"
    else:
        user, workspace = create_first_user_workspace(db, email=request.email, name=request.name, password=request.password)
        role = "admin"
    token = create_access_token(user.id, workspace.id)
    return {"access_token": token, "token_type": "bearer", "user": user_payload(user), "workspace": workspace_payload(workspace, role)}


@app.post("/api/auth/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email.lower()).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    membership = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).first()
    token = create_access_token(user.id, membership.workspace_id if membership else None)
    return {"access_token": token, "token_type": "bearer", "user": user_payload(user)}


@app.get("/api/auth/me")
def me(current_user: User = Depends(get_current_user), membership: WorkspaceMember = Depends(get_current_membership)):
    return {"user": user_payload(current_user), "membership": membership_payload(membership)}


@app.patch("/api/auth/me")
def update_me(request: UserProfileUpdateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    patch = request.model_dump(exclude_unset=True)
    user = db.get(User, current_user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if "name" in patch and patch["name"] is not None:
        user.name = patch["name"].strip()
    if "avatar_url" in patch:
        avatar_url = patch["avatar_url"] or ""
        if avatar_url and not avatar_url.startswith("data:image/"):
            raise HTTPException(status_code=400, detail="avatar_url must be an image data URL")
        user.avatar_url = avatar_url
    db.commit()
    db.refresh(user)
    return {"user": user_payload(user)}


@app.get("/api/workspaces/current")
def current_workspace(membership: WorkspaceMember = Depends(get_current_membership)):
    return {"workspace": workspace_payload(membership.workspace, membership.role), "membership": membership_payload(membership)}


@app.get("/api/workspaces/invites")
def list_invites(membership: WorkspaceMember = Depends(require_manager), db: Session = Depends(get_db)):
    if not settings.invite_api_enabled:
        raise HTTPException(status_code=404, detail="Invite API is disabled")
    invites = db.query(WorkspaceInvite).filter(WorkspaceInvite.workspace_id == membership.workspace_id).all()
    return {"items": [invite_payload(invite, include_token=False) for invite in invites]}


@app.get("/api/workspaces/members")
def list_members(membership: WorkspaceMember = Depends(require_manager), db: Session = Depends(get_db)):
    rows = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == membership.workspace_id)
        .order_by(WorkspaceMember.id.asc())
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "role": normalize_role(row.role),
                "user": user_payload(row.user),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@app.post("/api/workspaces/invites")
def create_invite(request: InviteCreateRequest, membership: WorkspaceMember = Depends(require_manager), db: Session = Depends(get_db)):
    if not settings.invite_api_enabled:
        raise HTTPException(status_code=404, detail="Invite API is disabled")
    if normalize_role(request.role) != "user":
        raise HTTPException(status_code=400, detail="Invite role must be user")
    invite = WorkspaceInvite(
        workspace_id=membership.workspace_id,
        email=request.email.lower(),
        role="user",
        token=secrets.token_urlsafe(24),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return {"invite": invite_payload(invite, include_token=False)}


@app.post("/api/workspaces/invites/accept")
def accept_invite(request: InviteAcceptRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not settings.invite_api_enabled:
        raise HTTPException(status_code=404, detail="Invite API is disabled")
    invite = db.query(WorkspaceInvite).filter(WorkspaceInvite.token == request.token, WorkspaceInvite.accepted_at.is_(None)).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    existing = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == invite.workspace_id, WorkspaceMember.user_id == current_user.id).first()
    if not existing:
        db.add(WorkspaceMember(workspace_id=invite.workspace_id, user_id=current_user.id, role=normalize_role(invite.role)))
    invite.accepted_at = __import__("datetime").datetime.utcnow()
    db.commit()
    return {"accepted": True}


@app.get("/api/tools")
def list_tools(membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    ensure_builtin_tools(db)
    tools = list_available_tools(db, workspace_id=membership.workspace_id, user_id=membership.user_id)
    return {"items": [tool_payload(tool) for tool in tools]}


@app.post("/api/tools")
def create_tool_endpoint(request: ToolRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    try:
        tool = create_tool(db, workspace_id=membership.workspace_id, user_id=membership.user_id, payload=request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tool": tool_payload(tool)}


@app.patch("/api/tools/{tool_id}")
def patch_tool_endpoint(tool_id: int, request: ToolUpdateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    tool = get_accessible_tool(db, workspace_id=membership.workspace_id, user_id=membership.user_id, tool_id=tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    try:
        tool = update_tool(db, tool=tool, payload=request.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"tool": tool_payload(tool)}


@app.delete("/api/tools/{tool_id}")
def delete_tool_endpoint(tool_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    tool = get_accessible_tool(db, workspace_id=membership.workspace_id, user_id=membership.user_id, tool_id=tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    try:
        delete_tool(db, tool=tool)
    except ValueError as exc:
        status_code = 409 if "in use" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"deleted": True}


@app.post("/api/tools/{tool_id}/test")
def test_tool_endpoint(tool_id: int, request: ToolTestRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    tool = get_accessible_tool(db, workspace_id=membership.workspace_id, user_id=membership.user_id, tool_id=tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return test_tool(tool, input_data=request.input, body=request.body)


@app.get("/api/prompt-templates")
def list_prompt_templates_endpoint(
    include_disabled: bool = Query(default=False),
    membership: WorkspaceMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    return {
        "items": list_prompt_templates(
            db,
            workspace_id=membership.workspace_id,
            user_id=membership.user_id,
            include_disabled=include_disabled,
        )
    }


@app.post("/api/prompt-templates")
def create_prompt_template_endpoint(
    request: PromptTemplateRequest,
    membership: WorkspaceMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    try:
        template = create_prompt_template(
            db,
            workspace_id=membership.workspace_id,
            user_id=membership.user_id,
            payload=request.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"template": prompt_template_payload(template)}


@app.patch("/api/prompt-templates/{template_id}")
def patch_prompt_template_endpoint(
    template_id: int,
    request: PromptTemplateUpdateRequest,
    membership: WorkspaceMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    template = get_owned_prompt_template(db, workspace_id=membership.workspace_id, user_id=membership.user_id, template_id=template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    try:
        template = update_prompt_template(db, template=template, payload=request.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"template": prompt_template_payload(template)}


@app.delete("/api/prompt-templates/{template_id}")
def delete_prompt_template_endpoint(template_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    template = get_owned_prompt_template(db, workspace_id=membership.workspace_id, user_id=membership.user_id, template_id=template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    delete_prompt_template(db, template=template)
    return {"deleted": True}


@app.post("/api/prompt-templates/copy-builtin")
def copy_builtin_prompt_template_endpoint(
    request: PromptTemplateCopyBuiltinRequest,
    membership: WorkspaceMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    try:
        template = copy_builtin_prompt_template(
            db,
            workspace_id=membership.workspace_id,
            user_id=membership.user_id,
            builtin_id=request.builtin_id,
            title=request.title,
        )
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"template": prompt_template_payload(template)}


@app.get("/api/models")
def list_models(
    include_disabled: bool = Query(default=False),
    membership: WorkspaceMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    ensure_default_models(db)
    query = db.query(ModelConfig)
    if include_disabled:
        if not can_manage(membership.role):
            raise HTTPException(status_code=403, detail="Admin role required")
    else:
        query = query.filter(ModelConfig.enabled.is_(True))
    models = query.order_by(ModelConfig.id.asc()).all()
    return {"items": [model_payload(model) for model in models]}


@app.post("/api/admin/models")
def create_model(request: ModelConfigRequest, _: WorkspaceMember = Depends(require_manager), db: Session = Depends(get_db)):
    if db.query(ModelConfig).filter(ModelConfig.model_name == request.model_name).first():
        raise HTTPException(status_code=409, detail="Model already exists")
    model = create_model_config(db, request.model_dump())
    return {"model": model_payload(model)}


@app.patch("/api/admin/models/{model_id}")
def patch_model(model_id: int, request: ModelConfigUpdateRequest, _: WorkspaceMember = Depends(require_manager), db: Session = Depends(get_db)):
    model = db.get(ModelConfig, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    payload = request.model_dump(exclude_unset=True)
    if "model_name" in payload and payload["model_name"] != model.model_name:
        existing = db.query(ModelConfig).filter(ModelConfig.model_name == payload["model_name"]).first()
        if existing:
            raise HTTPException(status_code=409, detail="Model already exists")
    model = update_model_config(db, model, payload)
    return {"model": model_payload(model)}


@app.delete("/api/admin/models/{model_id}")
def delete_model(model_id: int, _: WorkspaceMember = Depends(require_manager), db: Session = Depends(get_db)):
    model = db.get(ModelConfig, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    try:
        delete_model_config(db, model)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"deleted": True}


@app.get("/api/user-models")
def list_user_models(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    configs = list_user_model_configs(db, user_id=current_user.id)
    return {"items": [user_model_payload(config) for config in configs]}


@app.post("/api/user-models")
def create_user_model(request: UserModelConfigRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        config = create_user_model_config(db, user_id=current_user.id, payload=request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"model_config": user_model_payload(config)}


@app.post("/api/user-models/test")
def test_user_model_draft(request: UserModelCapabilityTestRequest, current_user: User = Depends(get_current_user)):
    try:
        payload = request.model_dump()
        detect_image = bool(payload.pop("detect_image", False))
        return test_user_model_payload(payload, detect_image=detect_image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/user-models/{config_id}")
def patch_user_model(
    config_id: int,
    request: UserModelConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = get_owned_user_model(db, user_id=current_user.id, config_id=config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Model config not found")
    try:
        config = update_user_model_config(db, config=config, payload=request.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"model_config": user_model_payload(config)}


@app.delete("/api/user-models/{config_id}")
def delete_user_model(config_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    config = get_owned_user_model(db, user_id=current_user.id, config_id=config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Model config not found")
    try:
        delete_user_model_config(db, config=config)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"deleted": True}


@app.post("/api/user-models/{config_id}/test")
def test_user_model(
    config_id: int,
    detect_image: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = get_owned_user_model(db, user_id=current_user.id, config_id=config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Model config not found")
    return test_user_model_config(config, detect_image=detect_image)


@app.post("/api/uploads")
def upload_file(request: UploadCreateRequest, membership: WorkspaceMember = Depends(get_current_membership), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        upload = create_upload(
            db,
            workspace_id=membership.workspace_id,
            user_id=current_user.id,
            filename=request.filename,
            content_type=request.content_type,
            content_base64=request.content_base64,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"upload": upload_payload(upload)}


@app.get("/api/agents")
def list_agents(membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    ensure_template_agents_published(db, membership.workspace_id)
    query = db.query(Agent).filter(Agent.workspace_id == membership.workspace_id)
    if not can_manage(membership.role):
        query = query.filter(Agent.created_by == membership.user_id)
    agents = query.order_by(Agent.updated_at.desc()).all()
    return {"items": [agent_summary(agent) for agent in agents]}


@app.post("/api/agents")
def create_agent_endpoint(request: AgentCreateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    try:
        validate_tool_ids(db, workspace_id=membership.workspace_id, user_id=membership.user_id, tool_ids=request.tool_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = apply_model_selection(db, request.model_dump(), user_id=membership.user_id)
    agent = create_agent(db, workspace_id=membership.workspace_id, user_id=membership.user_id, payload=payload)
    return {"agent": get_agent_detail(db, agent)}


@app.get("/api/agents/{agent_id}")
def get_agent(agent_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_read_access(agent, membership)
    return {"agent": get_agent_detail(db, agent)}


@app.patch("/api/agents/{agent_id}")
def patch_agent(agent_id: int, request: AgentUpdateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_write_access(agent, membership)
    if request.tool_ids is not None:
        try:
            validate_tool_ids(db, workspace_id=membership.workspace_id, user_id=membership.user_id, tool_ids=request.tool_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    agent = update_agent(db, agent, apply_model_selection(db, request.model_dump(exclude_unset=True), user_id=membership.user_id))
    return {"agent": get_agent_detail(db, agent)}


@app.get("/api/agents/{agent_id}/memory-profile")
def get_agent_memory_profile(agent_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_read_access(agent, membership)
    profile = get_memory_profile(
        db,
        workspace_id=membership.workspace_id,
        user_id=membership.user_id,
        agent_id=agent.id,
    )
    return {"profile": memory_profile_payload(profile, agent_id=agent.id)}


@app.patch("/api/agents/{agent_id}/memory-profile")
def patch_agent_memory_profile(
    agent_id: int,
    request: MemoryProfileUpdateRequest,
    membership: WorkspaceMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_read_access(agent, membership)
    try:
        profile = upsert_memory_profile(
            db,
            workspace_id=membership.workspace_id,
            user_id=membership.user_id,
            agent_id=agent.id,
            payload=request.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"profile": memory_profile_payload(profile)}


@app.delete("/api/agents/{agent_id}/memory-profile")
def delete_agent_memory_profile(agent_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_read_access(agent, membership)
    delete_memory_profile(
        db,
        workspace_id=membership.workspace_id,
        user_id=membership.user_id,
        agent_id=agent.id,
    )
    return {"deleted": True}


@app.delete("/api/agents/{agent_id}")
def delete_agent_endpoint(agent_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_write_access(agent, membership)
    try:
        delete_agent_service(db, agent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"deleted": True}


@app.post("/api/agents/{agent_id}/publish")
def publish_agent_endpoint(agent_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_write_access(agent, membership)
    require_review = not can_manage(membership.role)
    version = publish_agent(db, agent, membership.user_id, require_review=require_review)
    return {
        "status": agent.status,
        "review_required": require_review,
        "version": {"id": version.id, "version": version.version, "snapshot": version.snapshot},
    }


@app.get("/api/admin/agent-reviews")
def list_agent_reviews(membership: WorkspaceMember = Depends(require_manager), db: Session = Depends(get_db)):
    agents = (
        db.query(Agent)
        .filter(Agent.workspace_id == membership.workspace_id, Agent.status == "pending_review")
        .order_by(Agent.updated_at.desc())
        .all()
    )
    return {"items": [review_payload(db, agent) for agent in agents]}


@app.post("/api/admin/agent-reviews/{agent_id}/approve")
def approve_agent_review(agent_id: int, membership: WorkspaceMember = Depends(require_manager), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    if agent.status != "pending_review":
        raise HTTPException(status_code=400, detail="Agent is not pending review")
    version = approve_agent(db, agent, membership.user_id)
    return {"agent": get_agent_detail(db, agent), "version": {"id": version.id, "version": version.version}}


@app.post("/api/admin/agent-reviews/{agent_id}/reject")
def reject_agent_review(agent_id: int, membership: WorkspaceMember = Depends(require_manager), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    if agent.status != "pending_review":
        raise HTTPException(status_code=400, detail="Agent is not pending review")
    reject_agent(db, agent)
    return {"agent": get_agent_detail(db, agent)}


@app.get("/api/market/agents")
def list_market_agents(membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agents = (
        db.query(Agent)
        .filter(
            Agent.workspace_id == membership.workspace_id,
            Agent.status == "published",
            Agent.published_version_id.isnot(None),
        )
        .order_by(Agent.updated_at.desc())
        .all()
    )
    items = []
    for agent in agents:
        version = db.get(AgentVersion, agent.published_version_id) if agent.published_version_id else None
        items.append(market_agent_summary(agent, version))
    return {"items": items}


@app.post("/api/market/agents/{agent_id}/copy")
def copy_market_agent(agent_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    source = require_workspace_agent(db, membership.workspace_id, agent_id)
    if source.status != "published" or not source.published_version_id:
        raise HTTPException(status_code=404, detail="Market agent not found")
    try:
        copied = copy_agent_from_market(db, source=source, user_id=membership.user_id, workspace_id=membership.workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"agent": get_agent_detail(db, copied)}


@app.get("/api/agents/{agent_id}/versions")
def list_versions(agent_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_read_access(agent, membership)
    versions = db.query(AgentVersion).filter_by(agent_id=agent.id).order_by(AgentVersion.version.desc()).all()
    return {"items": [{"id": item.id, "version": item.version, "created_at": item.created_at.isoformat()} for item in versions]}


@app.get("/api/agents/{agent_id}/draft")
def get_draft(agent_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_write_access(agent, membership)
    return {"agent": get_agent_detail(db, agent)}


@app.get("/api/knowledge-bases")
def list_knowledge_bases(membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kbs = db.query(KnowledgeBase).filter(KnowledgeBase.workspace_id == membership.workspace_id).order_by(KnowledgeBase.id.desc()).all()
    items = []
    for kb in kbs:
        count = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == kb.id).count()
        items.append(knowledge_base_summary(kb, count))
    return {"items": items}


@app.post("/api/knowledge-bases")
def create_kb(request: KnowledgeBaseCreateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = create_knowledge_base(db, workspace_id=membership.workspace_id, user_id=membership.user_id, name=request.name, description=request.description)
    return {"knowledge_base": knowledge_base_summary(kb)}


@app.post("/api/knowledge-bases/{kb_id}/documents")
def upload_document(kb_id: int, request: KnowledgeDocumentCreateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    require_kb_write_access(kb, membership)
    try:
        document = add_document(
            db,
            workspace_id=membership.workspace_id,
            kb=kb,
            filename=request.filename,
            title=request.title,
            text=request.text,
            content=request.content,
            content_type=request.content_type,
            content_base64=request.content_base64,
            source_type=request.source_type,
        )
    except KnowledgeDocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        db.rollback()
        logger.exception("Knowledge document indexing failed")
        raise HTTPException(status_code=502, detail={"message": _sanitize_public_error(str(exc)), "error_code": "knowledge_index_failed"}) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Knowledge document upload failed")
        raise HTTPException(status_code=500, detail={"message": "Knowledge document upload failed.", "error_code": "knowledge_upload_failed"}) from exc
    payload = document_payload(document, db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).count())
    if document.status == "failed":
        raise HTTPException(status_code=422, detail={"message": document.error_message or "Document text extraction failed", "document": payload})
    return {"document": payload}


@app.get("/api/knowledge-bases/{kb_id}/documents")
def list_documents(kb_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    documents = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == kb.id).order_by(KnowledgeDocument.id.desc()).all()
    return {
        "items": [
            document_payload(
                document,
                db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).count(),
            )
            for document in documents
        ]
    }


@app.delete("/api/knowledge-bases/{kb_id}/documents/{document_id}")
def remove_document(kb_id: int, document_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    require_kb_write_access(kb, membership)
    document = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == kb.id, KnowledgeDocument.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    delete_document(db, workspace_id=membership.workspace_id, document=document)
    return {"deleted": True}


@app.post("/api/knowledge-bases/{kb_id}/index")
def index_kb(kb_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    require_kb_write_access(kb, membership)
    job_id = f"kb-{kb.id}-sync"
    summary = reindex_knowledge_base(db, workspace_id=membership.workspace_id, kb=kb)
    status = "failed" if summary["documents_failed"] and not summary["documents_indexed"] else "succeeded"
    payload = {
        "job_id": job_id,
        "knowledge_base_id": kb.id,
        "status": status,
        "message": (
            f"Rebuilt {summary['chunks_indexed']} chunks for {summary['documents_indexed']} documents."
            if status == "succeeded"
            else "Knowledge base reindex failed for all documents."
        ),
        **summary,
    }
    redis_store.set_job(job_id, payload)
    return payload


@app.get("/api/knowledge/jobs/{job_id}")
def get_knowledge_job(job_id: str, _: WorkspaceMember = Depends(get_current_membership)):
    lookup = redis_store.get_job(job_id)
    if lookup.hit and lookup.value:
        return lookup.value
    return {"job_id": job_id, "status": "unknown", "message": "Job state is not available or Redis is not configured."}


@app.delete("/api/knowledge-bases/{kb_id}")
def delete_kb(kb_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    require_kb_write_access(kb, membership)
    delete_knowledge_base(db, workspace_id=membership.workspace_id, kb=kb)
    return {"deleted": True}


@app.put("/api/knowledge-bases/{kb_id}")
def update_kb(kb_id: int, request: KnowledgeBaseCreateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    require_kb_write_access(kb, membership)
    kb.name = request.name
    kb.description = request.description
    db.commit()
    db.refresh(kb)
    return {"knowledge_base": knowledge_base_summary(kb)}


@app.get("/api/knowledge-bases/{kb_id}/documents/{document_id}/chunks")
def get_document_chunks(kb_id: int, document_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    document = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.knowledge_base_id == kb.id,
        KnowledgeDocument.id == document_id,
    ).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    chunks = list_document_chunks(db, document_id=document.id)
    return {"document": document_payload(document, len(chunks)), "chunks": chunks}


from pydantic import BaseModel

class ResegmentRequest(BaseModel):
    parse_mode: str = "precise"
    segment_mode: str = "auto"
    delimiter: str | None = "##"
    max_chunk_len: int = 5000
    overlap_pct: int = 10
    hierarchy_level: int = 3
    keep_hierarchy_info: bool = True

@app.post("/api/knowledge-bases/{kb_id}/documents/{document_id}/preview")
def preview_document_chunks(
    kb_id: int,
    document_id: int,
    request: ResegmentRequest,
    membership: WorkspaceMember = Depends(get_current_membership),
    db: Session = Depends(get_db)
):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    document = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.knowledge_base_id == kb.id,
        KnowledgeDocument.id == document_id
    ).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    cfg = request.model_dump()
    seg_mode = cfg.get("segment_mode", "auto")
    
    # 内存直接切分并不入库
    if seg_mode == "hierarchy":
        chunks = split_by_hierarchy(
            document.text,
            kb_id=kb.id,
            document_id=document.id,
            max_level=cfg.get("hierarchy_level", 3),
            keep_hierarchy_info=cfg.get("keep_hierarchy_info", True)
        )
    elif seg_mode == "custom":
        chunks = split_parent_child(
            document.text,
            kb_id=kb.id,
            document_id=document.id,
            parent_size=cfg.get("max_chunk_len", 1600),
            child_size=int(cfg.get("max_chunk_len", 1600) * 0.35),
            overlap=int(cfg.get("max_chunk_len", 1600) * cfg.get("overlap_pct", 10) / 100)
        )
    else:
        chunks = split_parent_child(document.text, kb_id=kb.id, document_id=document.id)
        
    return {
        "chunks_count": len(chunks),
        "preview_items": [
            {
                "chunk_index": idx,
                "text": chunk.get("text", ""),
                "hierarchy_path": chunk.get("section", "")
            }
            for idx, chunk in enumerate(chunks)
        ]
    }

@app.post("/api/knowledge-bases/{kb_id}/documents/{document_id}/resegment")
def resegment_document_chunks(
    kb_id: int,
    document_id: int,
    request: ResegmentRequest,
    membership: WorkspaceMember = Depends(get_current_membership),
    db: Session = Depends(get_db)
):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    require_kb_write_access(kb, membership)
    document = db.query(KnowledgeDocument).filter(
        KnowledgeDocument.knowledge_base_id == kb.id,
        KnowledgeDocument.id == document_id
    ).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # 保存配置并同步启动重新索引
    document.segment_config = request.model_dump()
    db.commit()
    
    try:
        chunk_count = index_document(
            db,
            workspace_id=membership.workspace_id,
            kb=kb,
            document=document,
            clear_existing=True
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail={"message": f"Resegment index failed: {str(exc)}"})
        
    return {"document": document_payload(document, chunk_count)}


@app.get("/api/agents/{agent_id}/workflow")
def get_workflow(agent_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_read_access(agent, membership)
    workflow = db.query(WorkflowDefinition).filter(WorkflowDefinition.agent_id == agent.id).first()
    return {"nodes": workflow.nodes if workflow else default_workflow()}


@app.patch("/api/agents/{agent_id}/workflow")
def update_workflow(agent_id: int, request: WorkflowUpdateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_write_access(agent, membership)
    validate_workflow_nodes(request.nodes)
    workflow = db.query(WorkflowDefinition).filter(WorkflowDefinition.agent_id == agent.id).first()
    if not workflow:
        workflow = WorkflowDefinition(agent_id=agent.id, nodes=request.nodes)
        db.add(workflow)
    else:
        workflow.nodes = request.nodes
    db.commit()
    return {"nodes": workflow.nodes}


@app.post("/api/agents/{agent_id}/chat/stream")
def chat_stream(agent_id: int, request: ChatRequest, membership: WorkspaceMember = Depends(get_current_membership), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    print(f"[DEBUG CHAT] agent_id: {agent_id} | mode: {request.mode} | session_id: {request.session_id}")
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_read_access(agent, membership)
    return StreamingResponse(stream_chat_events(db, agent, current_user.id, request), media_type="text/event-stream")


@app.get("/api/agents/{agent_id}/sessions")
def list_agent_sessions(agent_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    require_agent_read_access(agent, membership)
    query = db.query(ChatSession).filter(ChatSession.workspace_id == membership.workspace_id, ChatSession.agent_id == agent.id)
    if not can_manage(membership.role):
        query = query.filter(ChatSession.user_id == membership.user_id)
    sessions = query.order_by(ChatSession.updated_at.desc()).all()
    return {"items": [session_payload(session, db) for session in sessions]}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if not session or session.workspace_id != membership.workspace_id:
        raise HTTPException(status_code=404, detail="Session not found")
    require_session_access(session, membership)
    messages = db.query(Message).filter(Message.session_id == session.id).order_by(Message.id.asc()).all()
    return {"session": session_payload(session, db), "messages": [message_payload(message) for message in messages]}


@app.patch("/api/sessions/{session_id}")
def patch_session(session_id: int, request: SessionUpdateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if not session or session.workspace_id != membership.workspace_id:
        raise HTTPException(status_code=404, detail="Session not found")
    require_session_access(session, membership)
    session.title = request.title.strip()
    db.commit()
    db.refresh(session)
    return {"session": session_payload(session, db)}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if not session or session.workspace_id != membership.workspace_id:
        raise HTTPException(status_code=404, detail="Session not found")
    require_session_access(session, membership)

    message_ids = [
        row.id
        for row in db.query(Message.id).filter(Message.session_id == session.id).all()
    ]
    run_ids = [
        row.id
        for row in db.query(Run.id).filter(Run.session_id == session.id).all()
    ]
    if message_ids:
        db.query(Feedback).filter(Feedback.message_id.in_(message_ids)).delete(synchronize_session=False)
    if run_ids:
        db.query(RunStep).filter(RunStep.run_id.in_(run_ids)).delete(synchronize_session=False)
    db.query(SessionMemory).filter(SessionMemory.session_id == session.id).delete(synchronize_session=False)
    db.query(Message).filter(Message.session_id == session.id).delete(synchronize_session=False)
    db.query(Run).filter(Run.session_id == session.id).delete(synchronize_session=False)
    db.delete(session)
    db.commit()
    return {"deleted": True}


def stream_chat_events(db: Session, agent: Agent, user_id: int, request: ChatRequest) -> Iterable[str]:
    run = None
    try:
        session = get_or_create_session(db, agent, user_id, request.session_id, request.message)
        user_message = Message(session_id=session.id, role="user", content=request.message, sources=[])
        db.add(user_message)
        db.commit()
        runner = WorkflowRunner(db)
        answer = ""
        sources = []
        for event in runner.run_events(
            agent=agent,
            chat_session=session,
            user_message=request.message,
            mode=request.mode,
            variables=request.variables,
            rag_enabled=request.rag_enabled,
            rag_options=request.rag_options.model_dump(exclude_none=True) if request.rag_options else None,
            thinking_enabled=request.thinking_enabled,
            search_enabled=request.search_enabled,
            attachments=request.attachments,
        ):
            if event["event"] == "token":
                yield sse_event("token", {"content": event.get("content", "")})
            elif event["event"] == "step":
                step = event["step"]
                for runtime_event in step.get("events", []):
                    yield sse_event(runtime_event.get("event", "tool_call"), runtime_event.get("data", {}))
                yield sse_event("run_step", step)
            elif event["event"] == "complete":
                run = event["run"]
                answer = event["answer"]
                sources = event["sources"]
        if sources:
            yield sse_event("sources", {"items": sources})
        assistant = Message(session_id=session.id, role="assistant", content=answer, sources=sources)
        db.add(assistant)
        db.commit()
        db.refresh(assistant)
        yield sse_event("done", {"session_id": session.id, "message_id": assistant.id, "run_id": run.id, "content": answer})
    except Exception as exc:
        if run is not None:
            try:
                run.status = "failed"
                run.completed_at = __import__("datetime").datetime.utcnow()
                db.commit()
            except Exception:
                db.rollback()
        logger.exception("Agent chat stream failed")
        yield sse_event("error", safe_stream_error(exc))


@app.get("/api/runs/{run_id}")
def get_run(run_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if not run or run.workspace_id != membership.workspace_id:
        raise HTTPException(status_code=404, detail="Run not found")
    session = db.get(ChatSession, run.session_id)
    if session:
        require_session_access(session, membership)
    return {"run": {"id": run.id, "status": run.status, "agent_id": run.agent_id, "session_id": run.session_id}}


@app.get("/api/runs/{run_id}/steps")
def get_run_steps(run_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if not run or run.workspace_id != membership.workspace_id:
        raise HTTPException(status_code=404, detail="Run not found")
    session = db.get(ChatSession, run.session_id)
    if session:
        require_session_access(session, membership)
    steps = db.query(RunStep).filter(RunStep.run_id == run.id).order_by(RunStep.id.asc()).all()
    return {"items": [{"id": step.id, "node_id": step.node_id, "node_type": step.node_type, "status": step.status, "output": step.output} for step in steps]}


@app.post("/api/messages/{message_id}/feedback")
def create_feedback(
    message_id: int,
    request: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    membership: WorkspaceMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    message = db.get(Message, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    session = db.get(ChatSession, message.session_id)
    if not session or session.workspace_id != membership.workspace_id:
        raise HTTPException(status_code=404, detail="Message not found")
    require_session_access(session, membership)
    feedback = Feedback(message_id=message.id, user_id=current_user.id, rating=request.rating, comment=request.comment)
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return {"feedback": {"id": feedback.id, "rating": feedback.rating, "comment": feedback.comment}}


def user_payload(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "avatar_url": user.avatar_url or ""}


def workspace_payload(workspace, role: str) -> dict:
    return {"id": workspace.id, "name": workspace.name, "slug": workspace.slug, "role": normalize_role(role)}


def membership_payload(membership: WorkspaceMember) -> dict:
    return {"workspace_id": membership.workspace_id, "user_id": membership.user_id, "role": normalize_role(membership.role)}


def invite_payload(invite: WorkspaceInvite, *, include_token: bool = False) -> dict:
    payload = {"id": invite.id, "email": invite.email, "role": normalize_role(invite.role), "accepted_at": invite.accepted_at.isoformat() if invite.accepted_at else None}
    if include_token:
        payload["token"] = invite.token
    return payload


def session_payload(session: ChatSession, db: Session) -> dict:
    count = db.query(Message).filter(Message.session_id == session.id).count()
    return {
        "id": session.id,
        "agent_id": session.agent_id,
        "title": session.title,
        "message_count": count,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


def message_payload(message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "sources": message.sources or [],
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def invite_workspace(db: Session, workspace_id: int):
    from core.db.models import Workspace

    workspace = db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def require_workspace_agent(db: Session, workspace_id: int, agent_id: int) -> Agent:
    agent = db.query(Agent).filter(Agent.workspace_id == workspace_id, Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def require_agent_read_access(agent: Agent, membership: WorkspaceMember) -> None:
    if can_manage(membership.role):
        return
    if agent.created_by == membership.user_id:
        return
    raise HTTPException(status_code=403, detail="Agent access denied")


def require_agent_write_access(agent: Agent, membership: WorkspaceMember) -> None:
    if can_manage(membership.role):
        return
    if agent.created_by == membership.user_id:
        return
    raise HTTPException(status_code=403, detail="Agent edit denied")


def require_session_access(session: ChatSession, membership: WorkspaceMember) -> None:
    if can_manage(membership.role):
        return
    if session.user_id == membership.user_id:
        return
    raise HTTPException(status_code=404, detail="Session not found")


def review_payload(db: Session, agent: Agent) -> dict:
    version = db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).order_by(AgentVersion.version.desc()).first()
    return {
        **agent_summary(agent),
        "submitted_version": version.version if version else None,
        "submitted_at": version.created_at.isoformat() if version and version.created_at else None,
    }


def require_workspace_kb(db: Session, workspace_id: int, kb_id: int) -> KnowledgeBase:
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.workspace_id == workspace_id, KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


def require_kb_write_access(kb: KnowledgeBase, membership: WorkspaceMember) -> None:
    if can_manage(membership.role):
        return
    if kb.created_by == membership.user_id:
        return
    raise HTTPException(status_code=403, detail="Knowledge base edit denied")


def validate_workflow_nodes(nodes: list[dict]) -> None:
    allowed = {"Start", "LLM", "Knowledge", "Tool", "Answer"}
    seen = {node.get("type") for node in nodes}
    if not seen.issubset(allowed):
        raise HTTPException(status_code=400, detail="Unsupported workflow node type")
    if not {"Start", "Answer"}.issubset(seen):
        raise HTTPException(status_code=400, detail="Workflow requires Start and Answer nodes")


def apply_model_selection(db: Session, payload: dict, *, user_id: int) -> dict:
    if payload.get("user_model_config_id"):
        config = db.query(UserModelConfig).filter(
            UserModelConfig.id == payload["user_model_config_id"],
            UserModelConfig.user_id == user_id,
            UserModelConfig.enabled.is_(True),
        ).first()
        if not config:
            raise HTTPException(status_code=400, detail="User model config is not available")
        payload["model_id"] = None
        payload["model"] = config.chat_model
        if payload.get("temperature") is None:
            payload["temperature"] = config.default_temperature
        return payload
    if (
        not payload.get("model_id")
        and not payload.get("user_model_config_id")
        and "model_id" in payload
        and "user_model_config_id" in payload
    ):
        default_user_model = db.query(UserModelConfig).filter(
            UserModelConfig.user_id == user_id,
            UserModelConfig.enabled.is_(True),
            UserModelConfig.is_default.is_(True),
        ).order_by(UserModelConfig.id.asc()).first()
        if default_user_model:
            payload["user_model_config_id"] = default_user_model.id
            payload["model_id"] = None
            payload["model"] = default_user_model.chat_model
            if payload.get("temperature") is None:
                payload["temperature"] = default_user_model.default_temperature
            return payload
        payload["model"] = None
    if payload.get("model_id"):
        payload["user_model_config_id"] = None
    if not payload.get("model_id"):
        return payload
    model = db.get(ModelConfig, payload["model_id"])
    if not model or not model.enabled:
        raise HTTPException(status_code=400, detail="Model is not available")
    payload["model"] = model.model_name
    if payload.get("temperature") is None:
        payload["temperature"] = model.default_temperature
    return payload


def get_or_create_session(db: Session, agent: Agent, user_id: int, session_id: int | None, title_seed: str) -> ChatSession:
    if session_id:
        session = db.get(ChatSession, session_id)
        if session and session.agent_id == agent.id and session.user_id == user_id:
            return session
    session = ChatSession(workspace_id=agent.workspace_id, agent_id=agent.id, user_id=user_id, title=title_seed[:60] or "新对话")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def chunk_text(text: str, size: int = 28) -> Iterable[str]:
    for index in range(0, len(text), size):
        yield text[index : index + size]
