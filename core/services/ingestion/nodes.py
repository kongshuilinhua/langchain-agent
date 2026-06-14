from __future__ import annotations

from core.services.ingestion.pipeline import IngestionNode
from core.services.knowledge import _tokenize, chunk_document


class ChunkNode(IngestionNode):
    """按类型/策略分段，写 ctx.children / ctx.parents。"""

    name = "chunk"

    def run(self, ctx) -> None:
        children, parents = chunk_document(
            ctx.text,
            content_type=ctx.content_type,
            kb_id=ctx.knowledge_base_id,
            document_id=ctx.document_id,
            segment_config=ctx.segment_config,
        )
        ctx.children = children
        ctx.parents = parents


class EmbedNode(IngestionNode):
    """批量向量化 child，写 ctx.embeddings（与 ctx.children 对齐）。"""

    name = "embed"

    def __init__(self, provider) -> None:
        self.provider = provider

    def run(self, ctx) -> None:
        texts = [child["text"] for child in ctx.children]
        ctx.embeddings = self.provider.embed_batch(texts, runtime_config=ctx.runtime_config) if texts else []


class StoreNode(IngestionNode):
    """落库：写 KnowledgeChunk(child) + KnowledgeParentChunk(parent) + 向量 upsert(仅 child)。"""

    name = "store"

    def __init__(self, db, vector_store, *, title: str, filename: str, embedding_model: str) -> None:
        self.db = db
        self.vector_store = vector_store
        self.title = title
        self.filename = filename
        self.embedding_model = embedding_model

    def run(self, ctx) -> None:
        from core.db.models import KnowledgeChunk, KnowledgeParentChunk

        for index, (chunk_data, vector) in enumerate(zip(ctx.children, ctx.embeddings)):
            vector_id = chunk_data["chunk_id"]
            metadata = {
                "workspace_id": ctx.workspace_id,
                "knowledge_base_id": ctx.knowledge_base_id,
                "document_id": ctx.document_id,
                "chunk_id": vector_id,
                "parent_id": chunk_data["parent_id"],
                "filename": self.filename,
                "title": self.title,
                "page": chunk_data.get("page"),
                "section": chunk_data.get("section") or "",
                "content_hash": chunk_data["content_hash"],
                "tokens": _tokenize(chunk_data["text"]),
            }
            self.db.add(KnowledgeChunk(
                workspace_id=ctx.workspace_id,
                knowledge_base_id=ctx.knowledge_base_id,
                document_id=ctx.document_id,
                chunk_index=index,
                text=chunk_data["text"],
                vector_id=vector_id,
                parent_id=chunk_data["parent_id"],
                chunk_id=vector_id,
                title=self.title,
                page=chunk_data.get("page"),
                section=chunk_data.get("section") or "",
                content_hash=chunk_data["content_hash"],
                embedding_model=self.embedding_model,
                embedding_dimension=len(vector),
                metadata_=metadata,
            ))
            self.vector_store.upsert(vector_id, vector, chunk_data["text"], metadata)
        for parent in ctx.parents:
            self.db.add(KnowledgeParentChunk(
                workspace_id=ctx.workspace_id,
                knowledge_base_id=ctx.knowledge_base_id,
                document_id=ctx.document_id,
                parent_id=parent["parent_id"],
                text=parent["text"],
                content_hash=parent["content_hash"],
            ))
