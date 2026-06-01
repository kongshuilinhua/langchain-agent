from __future__ import annotations

import base64
import binascii
import hashlib
import re
from pathlib import Path
from sqlalchemy.orm import Session

from core.config import get_settings
from core.db.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from core.integrations.llm import OpenAICompatibleProvider
from core.integrations import vector_store as vector_store_module
from core.services.rag import retrieve, _tokenize
from core.services.uploads import DOC_TYPES, extract_document_text, sanitize_extracted_text


SUPPORTED_KNOWLEDGE_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".pdf", ".docx"}
SUPPORTED_TEXT_TYPES = {"text/plain", "text/markdown", "application/markdown", "text/csv"}
SUPPORTED_FILE_TYPES = DOC_TYPES


class KnowledgeDocumentError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400, record_failed: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.record_failed = record_failed


def create_knowledge_base(db: Session, *, workspace_id: int, user_id: int, name: str, description: str = "") -> KnowledgeBase:
    kb = KnowledgeBase(workspace_id=workspace_id, name=name, description=description, created_by=user_id)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb


def knowledge_base_summary(kb: KnowledgeBase, document_count: int = 0) -> dict:
    return {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description,
        "document_count": document_count,
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
    }


def document_payload(document: KnowledgeDocument, chunk_count: int = 0) -> dict:
    stored_chunk_count = getattr(document, "chunk_count", 0) or 0
    effective_chunk_count = stored_chunk_count if stored_chunk_count or document.status == "failed" else chunk_count
    text_preview = (getattr(document, "text_preview", "") or document.text or "")[:240]
    return {
        "id": document.id,
        "knowledge_base_id": document.knowledge_base_id,
        "filename": document.filename,
        "title": getattr(document, "title", "") or document.filename,
        "content_type": document.content_type,
        "source_type": getattr(document, "source_type", "text") or "text",
        "status": document.status,
        "chunk_count": effective_chunk_count,
        "text_preview": text_preview,
        "error_message": getattr(document, "error_message", "") or None,
        "segment_config": getattr(document, "segment_config", None),
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "updated_at": document.updated_at.isoformat() if getattr(document, "updated_at", None) else None,
    }


def add_document(
    db: Session,
    *,
    workspace_id: int,
    kb: KnowledgeBase,
    filename: str | None = None,
    text: str | None = None,
    content: str | None = None,
    content_type: str = "text/plain",
    source_type: str = "text",
    content_base64: str | None = None,
    title: str | None = None,
    runtime_config: dict | None = None,
) -> KnowledgeDocument:
    source_type = source_type or "text"
    filename = _safe_filename(filename or title or "document.txt")
    title = (title or filename).strip()[:255]
    try:
        prepared_text, normalized_filename, normalized_content_type = _prepare_document_payload(
            filename=filename,
            text=text,
            content=content,
            content_type=content_type,
            source_type=source_type,
            content_base64=content_base64,
        )
    except KnowledgeDocumentError as exc:
        if exc.record_failed:
            return _create_failed_document(
                db,
                kb=kb,
                filename=filename,
                title=title,
                content_type=content_type,
                source_type=source_type,
                error_message=str(exc),
            )
        raise

    document = KnowledgeDocument(
        knowledge_base_id=kb.id,
        filename=normalized_filename,
        title=title or normalized_filename,
        content_type=normalized_content_type,
        source_type=source_type,
        text=prepared_text,
        text_preview=_preview(prepared_text),
        chunk_count=0,
        error_message="",
        status="uploaded",
    )
    db.add(document)
    db.flush()
    index_document(
        db,
        workspace_id=workspace_id,
        kb=kb,
        document=document,
        runtime_config=runtime_config,
        clear_existing=False,
    )
    db.commit()
    db.refresh(document)
    return document


def reindex_knowledge_base(db: Session, *, workspace_id: int, kb: KnowledgeBase) -> dict:
    documents = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.knowledge_base_id == kb.id)
        .order_by(KnowledgeDocument.id.asc())
        .all()
    )
    indexed = 0
    failed = 0
    chunk_count = 0
    errors = []
    for document in documents:
        document_id = document.id
        filename = document.filename
        if not (document.text or "").strip():
            document.status = "failed"
            document.error_message = "Document has no extracted text to index"
            document.chunk_count = 0
            failed += 1
            errors.append({"document_id": document_id, "filename": filename, "error": document.error_message})
            db.commit()
            continue
        try:
            indexed_chunks = index_document(db, workspace_id=workspace_id, kb=kb, document=document, clear_existing=True)
            db.commit()
            chunk_count += indexed_chunks
            indexed += 1
        except Exception as exc:
            db.rollback()
            try:
                vector_store_module.vector_store.delete(
                    filters={"workspace_id": workspace_id, "knowledge_base_id": kb.id, "document_id": document_id}
                )
            except Exception:
                pass
            failed += 1
            document = db.get(KnowledgeDocument, document_id)
            if not document:
                errors.append({"document_id": document_id, "filename": filename, "error": _sanitize_error(str(exc))})
                continue
            db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document_id).delete(synchronize_session=False)
            document.status = "failed"
            document.error_message = _sanitize_error(str(exc))
            document.chunk_count = 0
            db.commit()
            errors.append({"document_id": document_id, "filename": filename, "error": document.error_message})
    return {
        "documents_total": len(documents),
        "documents_indexed": indexed,
        "documents_failed": failed,
        "chunks_indexed": chunk_count,
        "errors": errors[:10],
    }


def index_document(
    db: Session,
    *,
    workspace_id: int,
    kb: KnowledgeBase,
    document: KnowledgeDocument,
    runtime_config: dict | None = None,
    clear_existing: bool = True,
) -> int:
    if clear_existing:
        vector_store_module.vector_store.delete(
            filters={"workspace_id": workspace_id, "knowledge_base_id": kb.id, "document_id": document.id}
        )
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).delete(synchronize_session=False)

    document.status = "indexing"
    document.error_message = ""
    document.chunk_count = 0
    
    # 读取保存在文档中的分段配置规则
    cfg = document.segment_config or {}
    seg_mode = cfg.get("segment_mode", "auto")
    
    if seg_mode == "hierarchy":
        chunks = split_by_hierarchy(
            document.text,
            kb_id=kb.id,
            document_id=document.id,
            max_level=cfg.get("hierarchy_level", 3),
            keep_hierarchy_info=cfg.get("keep_hierarchy_info", True)
        )
    elif seg_mode == "custom":
        # 根据自定义参数运行 parent-child 分割
        chunks = split_parent_child(
            document.text,
            kb_id=kb.id,
            document_id=document.id,
            parent_size=cfg.get("max_chunk_len", 1600),
            child_size=int(cfg.get("max_chunk_len", 1600) * 0.35), # 等比例 child
            overlap=int(cfg.get("max_chunk_len", 1600) * cfg.get("overlap_pct", 10) / 100)
        )
    else:
        # 自动分段默认采用原系统的 split_parent_child 机制
        chunks = split_parent_child(document.text, kb_id=kb.id, document_id=document.id)
        
    provider = OpenAICompatibleProvider()
    settings = get_settings()
    for index, chunk_data in enumerate(chunks):
        chunk_text = chunk_data["text"]
        vector_id = chunk_data["chunk_id"]
        vector = provider.embed(chunk_text, runtime_config=runtime_config)
        metadata = {
            "workspace_id": workspace_id,
            "knowledge_base_id": kb.id,
            "document_id": document.id,
            "chunk_id": vector_id,
            "parent_id": chunk_data["parent_id"],
            "filename": document.filename,
            "title": document.title or document.filename,
            "page": chunk_data.get("page"),
            "section": chunk_data.get("section") or "",
            "content_hash": chunk_data["content_hash"],
            "tokens": _tokenize(chunk_text),
        }
        chunk = KnowledgeChunk(
            workspace_id=workspace_id,
            knowledge_base_id=kb.id,
            document_id=document.id,
            chunk_index=index,
            text=chunk_text,
            vector_id=vector_id,
            parent_id=chunk_data["parent_id"],
            chunk_id=vector_id,
            title=document.title or document.filename,
            page=chunk_data.get("page"),
            section=chunk_data.get("section") or "",
            content_hash=chunk_data["content_hash"],
            embedding_model=settings.openai_embedding_model,
            embedding_dimension=len(vector),
            metadata_=metadata,
        )
        db.add(chunk)
        vector_store_module.vector_store.upsert(
            vector_id,
            vector,
            chunk_text,
            metadata,
        )
    document.chunk_count = len(chunks)
    document.status = "indexed"
    return len(chunks)


def delete_document(db: Session, *, workspace_id: int, document: KnowledgeDocument) -> None:
    chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).all()
    vector_store_module.vector_store.delete(filters={"workspace_id": workspace_id, "knowledge_base_id": document.knowledge_base_id, "document_id": document.id})
    for chunk in chunks:
        db.delete(chunk)
    db.delete(document)
    db.commit()


def delete_knowledge_base(db: Session, *, workspace_id: int, kb: KnowledgeBase) -> None:
    documents = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == kb.id).all()
    for document in documents:
        vector_store_module.vector_store.delete(filters={"workspace_id": workspace_id, "knowledge_base_id": kb.id, "document_id": document.id})
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).delete(synchronize_session=False)
    db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == kb.id).delete(synchronize_session=False)
    db.delete(kb)
    db.commit()


def list_document_chunks(db: Session, *, document_id: int) -> list[dict]:
    chunks = (
        db.query(KnowledgeChunk)
        .filter(KnowledgeChunk.document_id == document_id)
        .order_by(KnowledgeChunk.chunk_index.asc())
        .all()
    )
    return [
        {
            "id": chunk.id,
            "chunk_index": chunk.chunk_index,
            "chunk_id": chunk.chunk_id or chunk.vector_id,
            "parent_id": chunk.parent_id or chunk.vector_id,
            "text": chunk.text,
            "vector_id": chunk.vector_id,
            "embedding_model": chunk.embedding_model or "",
            "embedding_dimension": chunk.embedding_dimension or 0,
            "content_hash": chunk.content_hash or "",
            "title": chunk.title or "",
            "page": chunk.page,
            "section": chunk.section or "",
        }
        for chunk in chunks
    ]


def search_knowledge(
    db: Session,
    *,
    workspace_id: int,
    knowledge_base_ids: list[int],
    query: str,
    top_k: int = 4,
    runtime_config: dict | None = None,
) -> list[dict]:
    result = retrieve(
        db,
        workspace_id=workspace_id,
        knowledge_base_ids=knowledge_base_ids,
        query=query,
        config={"top_k": top_k},
        runtime_config=runtime_config,
    )
    return result.sources


def split_text(text: str, *, chunk_size: int = 700) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    return [cleaned[index : index + chunk_size] for index in range(0, len(cleaned), chunk_size)]


def split_parent_child(
    text: str,
    *,
    kb_id: int,
    document_id: int,
    parent_size: int = 1600,
    child_size: int = 520,
    overlap: int = 80,
) -> list[dict]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    output = []
    parent_index = 0
    for parent_start in range(0, len(cleaned), parent_size):
        parent_text = cleaned[parent_start : parent_start + parent_size]
        parent_id = f"kb{kb_id}-doc{document_id}-parent{parent_index}"
        child_index = 0
        step = max(child_size - overlap, 1)
        for child_start in range(0, len(parent_text), step):
            child_text = parent_text[child_start : child_start + child_size].strip()
            if not child_text:
                continue
            chunk_id = f"{parent_id}-child{child_index}"
            output.append(
                {
                    "parent_id": parent_id,
                    "chunk_id": chunk_id,
                    "text": child_text,
                    "page": None,
                    "section": "",
                    "content_hash": hashlib.sha256(child_text.encode("utf-8")).hexdigest(),
                }
            )
            child_index += 1
        parent_index += 1
    return output


def split_by_hierarchy(
    text: str,
    *,
    kb_id: int,
    document_id: int,
    max_level: int = 3,
    keep_hierarchy_info: bool = True
) -> list[dict]:
    # 清理多余空格
    cleaned = text.strip()
    if not cleaned:
        return []

    heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    all_matches = list(heading_pattern.finditer(cleaned))

    if not all_matches:
        # 退化策略：无标题则调用默认 parent-child 块拆分
        return split_parent_child(cleaned, kb_id=kb_id, document_id=document_id)

    # 预先过滤出符合层级要求的标题
    matches = [m for m in all_matches if len(m.group(1)) <= max_level]

    if not matches:
        # 如果过滤后无标题，同样退化
        return split_parent_child(cleaned, kb_id=kb_id, document_id=document_id)

    chunks = []
    
    # 提取第一个标题之前的“前言/介绍”文本，防止这部分数据丢失
    first_heading_start = matches[0].start()
    intro_text = cleaned[0:first_heading_start].strip()
    if intro_text:
        parent_id = f"kb{kb_id}-doc{document_id}-intro"
        chunks.append({
            "parent_id": parent_id,
            "chunk_id": f"{parent_id}-chunk-intro",
            "text": intro_text,
            "page": None,
            "section": "前言" if keep_hierarchy_info else "",
            "content_hash": hashlib.sha256(intro_text.encode("utf-8")).hexdigest(),
        })

    # 层级路径栈，记录当前的 (level, heading_text) 元组
    path_stack: list[tuple[int, str]] = []

    for i, match in enumerate(matches):
        level = len(match.group(1)) # 几层 # 号
        heading_text = match.group(2).strip()

        # 计算正文起止点
        start_pos = match.end()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned)
        chunk_body = cleaned[start_pos:end_pos].strip()

        # 动态维护层级路径面包屑：若栈顶层级比当前层级更深或相等，则持续退栈
        while path_stack and path_stack[-1][0] >= level:
            path_stack.pop()
            
        path_stack.append((level, f"H{level}: {heading_text}"))
        
        section_path = " > ".join(item[1] for item in path_stack) if keep_hierarchy_info else ""
        parent_id = f"kb{kb_id}-doc{document_id}-hnode-{level}"

        if chunk_body:
            full_text = f"{heading_text}\n{chunk_body}"
            chunks.append({
                "parent_id": parent_id,
                "chunk_id": f"{parent_id}-chunk-{i}",
                "text": full_text,
                "page": None,
                "section": section_path,
                "content_hash": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
            })

    return chunks


def _prepare_document_payload(
    *,
    filename: str,
    text: str | None,
    content: str | None,
    content_type: str,
    source_type: str,
    content_base64: str | None,
) -> tuple[str, str, str]:
    normalized_filename = _safe_filename(filename)
    normalized_content_type = (content_type or "text/plain").strip().lower()
    if source_type == "text":
        payload_text = content if content is not None else text
        if payload_text is None or not payload_text.strip():
            raise KnowledgeDocumentError("Invalid document payload")
        payload_text = sanitize_extracted_text(payload_text)
        if not payload_text.strip():
            raise KnowledgeDocumentError("Invalid document payload")
        if normalized_content_type not in SUPPORTED_TEXT_TYPES:
            normalized_content_type = "text/plain"
        return payload_text, normalized_filename, normalized_content_type

    if source_type != "file":
        raise KnowledgeDocumentError("Invalid document payload")
    if not content_base64:
        raise KnowledgeDocumentError("Invalid document payload")
    if not _is_supported_file(normalized_filename, normalized_content_type):
        raise KnowledgeDocumentError("Unsupported file type")
    raw = _decode_base64(content_base64)
    if len(raw) > get_settings().upload_max_bytes:
        raise KnowledgeDocumentError("Document too large", status_code=413)
    try:
        extracted = sanitize_extracted_text(extract_document_text(normalized_filename, normalized_content_type, raw))
    except ValueError as exc:
        raise KnowledgeDocumentError("Document text extraction failed", status_code=422, record_failed=True) from exc
    if not extracted.strip():
        raise KnowledgeDocumentError("Document text extraction failed", status_code=422, record_failed=True)
    return extracted, normalized_filename, normalized_content_type


def _create_failed_document(
    db: Session,
    *,
    kb: KnowledgeBase,
    filename: str,
    title: str,
    content_type: str,
    source_type: str,
    error_message: str,
) -> KnowledgeDocument:
    document = KnowledgeDocument(
        knowledge_base_id=kb.id,
        filename=_safe_filename(filename),
        title=(title or filename)[:255],
        content_type=(content_type or "application/octet-stream")[:120],
        source_type=source_type,
        text="",
        text_preview="",
        chunk_count=0,
        error_message=_sanitize_error(error_message),
        status="failed",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _safe_filename(filename: str) -> str:
    cleaned = Path(filename).name.strip()
    return cleaned[:255] or "document.txt"


def _preview(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:240]


def _is_supported_file(filename: str, content_type: str) -> bool:
    suffix = Path(filename).suffix.lower()
    return content_type in SUPPORTED_FILE_TYPES or suffix in SUPPORTED_KNOWLEDGE_SUFFIXES


def _decode_base64(content_base64: str) -> bytes:
    payload = content_base64.split(",", 1)[1] if content_base64.startswith("data:") and "," in content_base64 else content_base64
    try:
        return base64.b64decode(payload, validate=True)
    except binascii.Error as exc:
        raise KnowledgeDocumentError("Invalid document payload") from exc


def _sanitize_error(message: str) -> str:
    cleaned = re.sub(r"[A-Za-z]:\\[^\s]+", "[path]", str(message))
    cleaned = re.sub(r"(?i)(sk-[A-Za-z0-9_-]+|api[_-]?key\s*[:=]\s*\S+|secret\s*[:=]\s*\S+)", "[secret]", cleaned)
    cleaned = cleaned.replace("\n", " ").replace("\r", " ").strip()
    return cleaned[:300] or "Document text extraction failed"
