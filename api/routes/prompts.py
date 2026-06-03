"""灵枢 Agent 平台 —— 提示词模板路由。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.deps import get_current_membership
from api.schemas import (
    PromptTemplateCopyBuiltinRequest,
    PromptTemplateRequest,
    PromptTemplateUpdateRequest,
)
from core.db.models import WorkspaceMember
from core.db.session import get_db
from core.services.prompt_templates import (
    copy_builtin_prompt_template,
    create_prompt_template,
    delete_prompt_template,
    get_owned_prompt_template,
    list_prompt_templates,
    prompt_template_payload,
    update_prompt_template,
)

router = APIRouter(prefix="/api/prompt-templates", tags=["prompts"])


@router.get("")
def list_prompt_templates_endpoint(
    include_disabled: bool = Query(default=False),
    membership: WorkspaceMember = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    return {
        "items": list_prompt_templates(
            db, workspace_id=membership.workspace_id, user_id=membership.user_id, include_disabled=include_disabled
        )
    }


@router.post("")
def create_prompt_template_endpoint(request: PromptTemplateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    try:
        template = create_prompt_template(db, workspace_id=membership.workspace_id, user_id=membership.user_id, payload=request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"template": prompt_template_payload(template)}


@router.patch("/{template_id}")
def patch_prompt_template_endpoint(template_id: int, request: PromptTemplateUpdateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    template = get_owned_prompt_template(db, workspace_id=membership.workspace_id, user_id=membership.user_id, template_id=template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    try:
        template = update_prompt_template(db, template=template, payload=request.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"template": prompt_template_payload(template)}


@router.delete("/{template_id}")
def delete_prompt_template_endpoint(template_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    template = get_owned_prompt_template(db, workspace_id=membership.workspace_id, user_id=membership.user_id, template_id=template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    delete_prompt_template(db, template=template)
    return {"deleted": True}


@router.post("/copy-builtin")
def copy_builtin_prompt_template_endpoint(request: PromptTemplateCopyBuiltinRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    try:
        template = copy_builtin_prompt_template(db, workspace_id=membership.workspace_id, user_id=membership.user_id, builtin_id=request.builtin_id, title=request.title)
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"template": prompt_template_payload(template)}
