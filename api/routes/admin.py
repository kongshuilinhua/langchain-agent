"""灵枢 Agent 平台 —— Admin 路由（审核 + 市场 + 成员管理）。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.access import require_workspace_agent
from api.deps import get_current_membership, get_current_user, require_manager
from api.schemas import UploadCreateRequest
from api.serializers import review_payload
from core.db.models import (
    Agent,
    AgentVersion,
    User,
    WorkspaceMember,
)
from core.db.session import get_db
from core.services.agents import (
    approve_agent,
    get_agent_detail,
    market_agent_summary,
    reject_agent,
)
from core.services.uploads import create_upload, upload_payload
from core.services.agents import copy_agent_from_market

router = APIRouter(tags=["admin"])


# ── Agent Reviews ──

@router.get("/api/admin/agent-reviews")
def list_agent_reviews(membership: WorkspaceMember = Depends(require_manager), db: Session = Depends(get_db)):
    agents = db.query(Agent).filter(Agent.workspace_id == membership.workspace_id, Agent.status == "pending_review").order_by(Agent.updated_at.desc()).all()
    return {"items": [review_payload(db, agent) for agent in agents]}


@router.post("/api/admin/agent-reviews/{agent_id}/approve")
def approve_agent_review(agent_id: int, membership: WorkspaceMember = Depends(require_manager), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    if agent.status != "pending_review":
        raise HTTPException(status_code=400, detail="Agent is not pending review")
    version = approve_agent(db, agent, membership.user_id)
    return {"agent": get_agent_detail(db, agent), "version": {"id": version.id, "version": version.version}}


@router.post("/api/admin/agent-reviews/{agent_id}/reject")
def reject_agent_review(agent_id: int, membership: WorkspaceMember = Depends(require_manager), db: Session = Depends(get_db)):
    agent = require_workspace_agent(db, membership.workspace_id, agent_id)
    if agent.status != "pending_review":
        raise HTTPException(status_code=400, detail="Agent is not pending review")
    reject_agent(db, agent)
    return {"agent": get_agent_detail(db, agent)}


# ── Market ──

@router.get("/api/market/agents")
def list_market_agents(membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    agents = db.query(Agent).filter(
        Agent.workspace_id == membership.workspace_id, Agent.status == "published", Agent.published_version_id.isnot(None),
    ).order_by(Agent.updated_at.desc()).all()
    items = []
    for agent in agents:
        version = db.get(AgentVersion, agent.published_version_id) if agent.published_version_id else None
        items.append(market_agent_summary(agent, version))
    return {"items": items}


@router.post("/api/market/agents/{agent_id}/copy")
def copy_market_agent(agent_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    source = require_workspace_agent(db, membership.workspace_id, agent_id)
    if source.status != "published" or not source.published_version_id:
        raise HTTPException(status_code=404, detail="Market agent not found")
    try:
        copied = copy_agent_from_market(db, source=source, user_id=membership.user_id, workspace_id=membership.workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"agent": get_agent_detail(db, copied)}


# ── Uploads ──

@router.post("/api/uploads")
def upload_file(request: UploadCreateRequest, membership: WorkspaceMember = Depends(get_current_membership), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        upload = create_upload(db, workspace_id=membership.workspace_id, user_id=current_user.id, filename=request.filename, content_type=request.content_type, content_base64=request.content_base64)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"upload": upload_payload(upload)}
