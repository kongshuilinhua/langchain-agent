"""
灵枢 Agent 平台 —— FastAPI 应用入口。

🎯 架构角色：
    应用工厂 + 全局基础设施（CORS、异常处理、限流、健康检查、启动钩子）。
    API 端点已拆分到 api/routes/ 目录下的独立模块中，本文件只负责挂载 Router。

    路由分布：
    - api/routes/auth.py       → /api/auth/*
    - api/routes/workspace.py  → /api/workspaces/*
    - api/routes/agents.py     → /api/agents/*
    - api/routes/knowledge.py  → /api/knowledge-bases/*
    - api/routes/tools.py      → /api/tools/*
    - api/routes/models.py     → /api/models/*, /api/admin/models/*, /api/user-models/*
    - api/routes/prompts.py    → /api/prompt-templates/*
    - api/routes/admin.py      → /api/admin/agent-reviews/*, /api/market/*, /api/uploads
    - api/routes/chat.py       → /api/agents/{id}/chat/stream, /api/sessions/*, /api/runs/*, /api/messages/*
    - api/routes/search.py     → /api/search/test, /api/knowledge/jobs/*
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from api.rate_limit import limiter
from core.config import get_settings
from core.db.session import engine, init_db
from core.exceptions import AppException
from core.integrations.llm import DASHSCOPE_COMPATIBLE_BASE, OPENAI_COMPATIBLE_DEFAULT_BASE, OpenAICompatibleProvider
from core.integrations.vector_store import vector_store
from core.security.api_keys import secret_storage_ready
from core.services.rag_cache import redis_store

from api.routes.auth import router as auth_router
from api.routes.workspace import router as workspace_router
from api.routes.agents import router as agents_router
from api.routes.knowledge import router as knowledge_router
from api.routes.tools import router as tools_router
from api.routes.models import router as models_router
from api.routes.prompts import router as prompts_router
from api.routes.admin import router as admin_router
from api.routes.chat import router as chat_router
from api.routes.search import router as search_router

# ── 应用初始化 ────────────────────────────────────────────

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


@app.exception_handler(AppException)
def app_exception_handler(request, exc: AppException):
    """平台统一异常拦截器。参考 Ragent GlobalExceptionHandler 设计。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code.code, "message": exc.message},
    )


# Rate Limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── 启动钩子 ──────────────────────────────────────────────

@app.on_event("startup")
def startup() -> None:
    global startup_error
    if settings.jwt_secret == "change-me-in-production":
        logger.warning(
            "SECURITY WARNING: JWT_SECRET is using the insecure default value. "
            "Set a strong random secret via the JWT_SECRET environment variable."
        )
    try:
        from core.integrations.langsmith_setup import configure_langsmith

        configure_langsmith()
    except Exception:
        logger.exception("LangSmith configuration failed; tracing remains disabled")
    try:
        init_db()
        startup_error = None
        # 崩溃恢复：复位上次进程退出时卡在 indexing 的文档（后台入库任务随进程丢失）。
        try:
            from core.db.session import SessionLocal
            from core.services.knowledge import recover_interrupted_ingestion

            with SessionLocal() as recovery_session:
                recovered = recover_interrupted_ingestion(recovery_session)
            if recovered:
                logger.warning("Reset %d document(s) stuck in 'indexing' after restart", recovered)
        except Exception:
            logger.exception("Failed to recover interrupted ingestion on startup")
    except Exception as exc:
        startup_error = str(exc)[:500]
        logger.exception("Database initialization failed; API started in degraded mode")


# ── 健康检查 ──────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """系统就绪度与依赖健康性自检大盘。Phase 5: DB + Chat + Embedding 三路探针并行执行。"""
    loop = asyncio.get_running_loop()
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

    # 🎯 Phase 5: 三个独立探针并行执行（DB / Chat / Embedding）
    db_future = loop.run_in_executor(None, _probe_database)
    chat_enabled = bool(settings.health_model_probe_enabled and not model_mock)
    embed_enabled = bool(settings.health_model_probe_enabled and not embedding_mock and embedding_model)
    chat_future = loop.run_in_executor(None, lambda: _model_probe("chat", enabled=chat_enabled))
    embed_future = loop.run_in_executor(None, lambda: _model_probe("embedding", enabled=embed_enabled))
    database_status = await db_future
    model_probe = await chat_future
    embedding_probe = await embed_future

    issues = []
    if not database_status["available"]:
        issues.append("Database is configured but not reachable.")
    if not secret_storage_ready():
        issues.append("API_KEY_ENCRYPTION_KEY is required before storing user model keys or tool secrets.")
    if startup_error:
        issues.append("Database initialization failed during startup.")
    redis_status = redis_store.status()
    vector_status = vector_store.status()
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
                "available": bool(embedding_model and embedding_api_key and not embedding_mock and embedding_probe.get("ok", False)),
                "reason": None if bool(embedding_model and embedding_api_key and not embedding_mock and embedding_probe.get("ok", False)) else _runtime_unavailable_reason(embedding_probe, vector_status),
                "probe": embedding_probe,
            },
            "web_search": {
                "provider": settings.web_search_provider,
                "enabled": settings.web_search_enabled,
                "configured": settings.web_search_enabled and settings.web_search_provider == "duckduckgo_html",
                "requires_api_key": False,
                "top_k": settings.web_search_top_k,
            },
            "secret_storage": {"configured": secret_storage_ready()},
        },
    }


def _probe_database() -> dict:
    """Phase 5: 独立数据库探针，供 health() 并行调用。"""
    status = {"configured": bool(settings.database_url), "available": False, "error": None}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        status["available"] = True
    except Exception as exc:
        status["error"] = str(exc)[:240]
    return status


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
                settings_obj.deepseek_api_key and (
                    (settings_obj.openai_api_base or "").rstrip("/") == settings_obj.deepseek_api_base.rstrip("/")
                    or settings_obj.openai_model == settings_obj.deepseek_model
                )
            )
            model = settings_obj.deepseek_model if use_deepseek else settings_obj.openai_model
            provider._post_json(
                provider._api_base(settings_obj, purpose="chat").rstrip("/") + "/chat/completions",
                {"model": model, "messages": [{"role": "user", "content": "health"}], "temperature": 0, "stream": False},
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


# ── 路由挂载 ──────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(workspace_router)
app.include_router(agents_router)
app.include_router(knowledge_router)
app.include_router(tools_router)
app.include_router(models_router)
app.include_router(prompts_router)
app.include_router(admin_router)
app.include_router(chat_router)
app.include_router(search_router)
