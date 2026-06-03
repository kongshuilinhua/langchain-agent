"""灵枢 Agent 平台 —— 知识库路由。"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.access import require_kb_write_access, require_workspace_kb
from api.deps import get_current_membership
from api.schemas import KnowledgeBaseCreateRequest, KnowledgeDocumentCreateRequest
from core.db.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument, WorkspaceMember
from core.db.session import get_db
from core.services.knowledge import (
    KnowledgeDocumentError,
    add_document,
    create_knowledge_base,
    delete_document,
    delete_knowledge_base,
    document_payload,
    index_document,
    knowledge_base_summary,
    list_document_chunks,
    reindex_knowledge_base,
    split_by_hierarchy,
    split_parent_child,
)
from core.services.rag_cache import redis_store

from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge"])


class ResegmentRequest(BaseModel):
    parse_mode: str = "precise"
    segment_mode: str = "auto"
    delimiter: str | None = "##"
    max_chunk_len: int = 5000
    overlap_pct: int = 10
    hierarchy_level: int = 3
    keep_hierarchy_info: bool = True


@router.get("")
def list_knowledge_bases(membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kbs = db.query(KnowledgeBase).filter(KnowledgeBase.workspace_id == membership.workspace_id).order_by(KnowledgeBase.id.desc()).all()
    # 🎯 N+1 优化：JOIN + GROUP BY 一次查询获取所有知识库的文档计数
    kb_ids = [kb.id for kb in kbs]
    counts: dict[int, int] = {}
    if kb_ids:
        rows = (
            db.query(
                KnowledgeDocument.knowledge_base_id,
                func.count(KnowledgeDocument.id),
            )
            .filter(KnowledgeDocument.knowledge_base_id.in_(kb_ids))
            .group_by(KnowledgeDocument.knowledge_base_id)
            .all()
        )
        counts = {kb_id: cnt for kb_id, cnt in rows}
    items = [knowledge_base_summary(kb, counts.get(kb.id, 0)) for kb in kbs]
    return {"items": items}


@router.post("")
def create_kb(request: KnowledgeBaseCreateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = create_knowledge_base(db, workspace_id=membership.workspace_id, user_id=membership.user_id, name=request.name, description=request.description)
    return {"knowledge_base": knowledge_base_summary(kb)}


@router.post("/{kb_id}/documents")
def upload_document(kb_id: int, request: KnowledgeDocumentCreateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    require_kb_write_access(kb, membership)
    try:
        document = add_document(
            db, workspace_id=membership.workspace_id, kb=kb,
            filename=request.filename, title=request.title, text=request.text,
            content=request.content, content_type=request.content_type,
            content_base64=request.content_base64, source_type=request.source_type,
        )
    except KnowledgeDocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        db.rollback()
        logger.exception("Knowledge document indexing failed")
        raise HTTPException(status_code=502, detail={"message": str(exc)[:500], "error_code": "knowledge_index_failed"}) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Knowledge document upload failed")
        raise HTTPException(status_code=500, detail={"message": "Knowledge document upload failed.", "error_code": "knowledge_upload_failed"}) from exc
    payload = document_payload(document, db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).count())
    if document.status == "failed":
        raise HTTPException(status_code=422, detail={"message": document.error_message or "Document text extraction failed", "document": payload})
    return {"document": payload}


@router.get("/{kb_id}/documents")
def list_documents(kb_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    documents = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == kb.id).order_by(KnowledgeDocument.id.desc()).all()
    return {
        "items": [
            document_payload(doc, db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id).count())
            for doc in documents
        ]
    }


@router.delete("/{kb_id}/documents/{document_id}")
def remove_document(kb_id: int, document_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    require_kb_write_access(kb, membership)
    document = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == kb.id, KnowledgeDocument.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    delete_document(db, workspace_id=membership.workspace_id, document=document)
    return {"deleted": True}


@router.post("/{kb_id}/index")
def index_kb(kb_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    require_kb_write_access(kb, membership)
    summary = reindex_knowledge_base(db, workspace_id=membership.workspace_id, kb=kb)
    status = "failed" if summary["documents_failed"] and not summary["documents_indexed"] else "succeeded"
    job_id = f"kb-{kb.id}-sync"
    payload = {
        "job_id": job_id, "knowledge_base_id": kb.id, "status": status,
        "message": (
            f"Rebuilt {summary['chunks_indexed']} chunks for {summary['documents_indexed']} documents."
            if status == "succeeded" else "Knowledge base reindex failed for all documents."
        ),
        **summary,
    }
    redis_store.set_job(job_id, payload)
    return payload


@router.get("/{kb_id}/documents/{document_id}/chunks")
def get_document_chunks(kb_id: int, document_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    document = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == kb.id, KnowledgeDocument.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    chunks = list_document_chunks(db, document_id=document.id)
    return {"document": document_payload(document, len(chunks)), "chunks": chunks}


@router.post("/{kb_id}/documents/{document_id}/preview")
def preview_document_chunks(kb_id: int, document_id: int, request: ResegmentRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    document = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == kb.id, KnowledgeDocument.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    cfg = request.model_dump()
    seg_mode = cfg.get("segment_mode", "auto")
    if seg_mode == "hierarchy":
        chunks = split_by_hierarchy(document.text, kb_id=kb.id, document_id=document.id, max_level=cfg.get("hierarchy_level", 3), keep_hierarchy_info=cfg.get("keep_hierarchy_info", True))
    elif seg_mode == "custom":
        chunks = split_parent_child(document.text, kb_id=kb.id, document_id=document.id, parent_size=cfg.get("max_chunk_len", 1600), child_size=int(cfg.get("max_chunk_len", 1600) * 0.35), overlap=int(cfg.get("max_chunk_len", 1600) * cfg.get("overlap_pct", 10) / 100))
    else:
        chunks = split_parent_child(document.text, kb_id=kb.id, document_id=document.id)
    return {"chunks_count": len(chunks), "preview_items": [{"chunk_index": idx, "text": chunk.get("text", ""), "hierarchy_path": chunk.get("section", "")} for idx, chunk in enumerate(chunks)]}


@router.post("/{kb_id}/documents/{document_id}/resegment")
def resegment_document_chunks(kb_id: int, document_id: int, request: ResegmentRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    require_kb_write_access(kb, membership)
    document = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == kb.id, KnowledgeDocument.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    document.segment_config = request.model_dump()
    db.commit()
    try:
        chunk_count = index_document(db, workspace_id=membership.workspace_id, kb=kb, document=document, clear_existing=True)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail={"message": f"Resegment index failed: {str(exc)}"})
    return {"document": document_payload(document, chunk_count)}


@router.delete("/{kb_id}")
def delete_kb(kb_id: int, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    require_kb_write_access(kb, membership)
    delete_knowledge_base(db, workspace_id=membership.workspace_id, kb=kb)
    return {"deleted": True}


@router.patch("/{kb_id}")
def update_kb(kb_id: int, request: KnowledgeBaseCreateRequest, membership: WorkspaceMember = Depends(get_current_membership), db: Session = Depends(get_db)):
    kb = require_workspace_kb(db, membership.workspace_id, kb_id)
    require_kb_write_access(kb, membership)
    kb.name = request.name
    kb.description = request.description
    db.commit()
    db.refresh(kb)
    return {"knowledge_base": knowledge_base_summary(kb)}
