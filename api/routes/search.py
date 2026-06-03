"""灵枢 Agent 平台 —— Web 搜索测试路由。"""

from fastapi import APIRouter, Depends, Query

from api.deps import get_current_membership
from core.config import get_settings
from core.db.models import WorkspaceMember
from core.services.web_search import search_web

router = APIRouter(tags=["search"])
settings = get_settings()


@router.get("/api/search/test")
def test_web_search(q: str = Query(min_length=1, max_length=300), membership: WorkspaceMember = Depends(get_current_membership)):
    try:
        return {"ok": True, **search_web(q)}
    except ValueError as exc:
        return {"ok": False, "query": q, "provider": settings.web_search_provider, "items": [], "error_code": str(exc)}


@router.get("/api/knowledge/jobs/{job_id}")
def get_knowledge_job(job_id: str, _: WorkspaceMember = Depends(get_current_membership)):
    from core.services.rag_cache import redis_store
    lookup = redis_store.get_job(job_id)
    if lookup.hit and lookup.value:
        return lookup.value
    return {"job_id": job_id, "status": "unknown", "message": "Job state is not available or Redis is not configured."}
