from __future__ import annotations

import argparse
from importlib.metadata import version
import json
import math
from pathlib import Path
import sys
import uuid
import warnings


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _eligible_cases(cases: list[dict], limit: int) -> tuple[list[dict], list[dict]]:
    selected = []
    skipped = []
    for case in cases:
        if case.get("should_refuse"):
            skipped.append({"id": case.get("id"), "reason": "should_refuse"})
            continue
        if case.get("intent") == "chitchat":
            skipped.append({"id": case.get("id"), "reason": "not_a_rag_case"})
            continue
        selected.append(case)
        if len(selected) >= limit:
            break
    return selected, skipped


def _find_case_target(db, case: dict):
    from sqlalchemy import or_

    from core.db.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument

    expected = [str(item).strip() for item in case.get("expected_sources") or [] if str(item).strip()]
    if not expected:
        return None
    filters = []
    for name in expected:
        filters.extend(
            [
                KnowledgeDocument.filename.ilike(f"%{name}%"),
                KnowledgeDocument.title.ilike(f"%{name}%"),
            ]
        )
    return (
        db.query(KnowledgeBase.workspace_id, KnowledgeBase.id)
        .join(KnowledgeDocument, KnowledgeDocument.knowledge_base_id == KnowledgeBase.id)
        .join(KnowledgeChunk, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .filter(or_(*filters))
        .first()
    )


def _seed_text(case: dict) -> str:
    case_id = case.get("id")
    if case_id == "hybrid-basic":
        return "hybrid-source-token 是用于验证 Dense、BM25 与 RRF 混合检索链路的测试标记。"
    if case_id == "coref-1":
        return "产品手册：灵枢扫地机器人整机保修期为12个月，电池保修期为6个月。"
    keywords = "、".join(case.get("keywords") or []) or case.get("question", "评测知识")
    return f"评测知识条目：{keywords}。"


def _ensure_temp_target(db, case: dict, temp_state: dict):
    from core.config import get_settings
    from core.db.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument, User, Workspace
    from core.integrations import vector_store as vector_store_module
    from core.integrations.llm import OpenAICompatibleProvider

    if temp_state.get("kb") is None:
        workspace = db.query(Workspace).order_by(Workspace.id.asc()).first()
        user = db.query(User).order_by(User.id.asc()).first()
        if workspace is None or user is None:
            raise RuntimeError("live eval needs at least one existing workspace and user")
        kb = KnowledgeBase(
            workspace_id=workspace.id,
            name=f"ragas-live-eval-{uuid.uuid4().hex[:8]}",
            description="Temporary Ragas evaluation fixture",
            created_by=user.id,
        )
        db.add(kb)
        db.flush()
        temp_state["kb"] = kb
        temp_state["workspace_id"] = workspace.id

    kb = temp_state["kb"]
    expected = case.get("expected_sources") or [f"{case.get('id', 'case')}.txt"]
    filename = str(expected[0])
    if "." not in filename:
        filename += ".txt"
    text = _seed_text(case)
    document = KnowledgeDocument(
        knowledge_base_id=kb.id,
        filename=filename,
        title=filename.rsplit(".", 1)[0],
        content_type="text/plain",
        source_type="text",
        text=text,
        text_preview=text,
        chunk_count=1,
        status="success",
    )
    db.add(document)
    db.flush()

    settings = get_settings()
    provider = OpenAICompatibleProvider()
    vector = provider.embed(text)
    vector_id = f"ragas-eval-{uuid.uuid4().hex}"
    chunk_id = f"ragas-eval-kb{kb.id}-doc{document.id}-chunk0"
    metadata = {
        "workspace_id": kb.workspace_id,
        "knowledge_base_id": kb.id,
        "document_id": document.id,
        "chunk_id": chunk_id,
        "parent_id": chunk_id,
        "filename": filename,
        "title": document.title,
        "page": None,
        "section": "evaluation",
        "content_hash": uuid.uuid5(uuid.NAMESPACE_URL, text).hex,
    }
    db.add(
        KnowledgeChunk(
            workspace_id=kb.workspace_id,
            knowledge_base_id=kb.id,
            document_id=document.id,
            chunk_index=0,
            text=text,
            vector_id=vector_id,
            parent_id=chunk_id,
            chunk_id=chunk_id,
            title=document.title,
            section="evaluation",
            content_hash=metadata["content_hash"],
            embedding_model=settings.openai_embedding_model,
            embedding_dimension=len(vector),
            metadata_=metadata,
        )
    )
    db.commit()
    vector_store_module.vector_store.upsert(vector_id, vector, text, metadata)
    return kb.workspace_id, kb.id


def _embedding_model():
    from langchain_openai import OpenAIEmbeddings

    from core.config import get_settings
    from core.integrations.llm import OpenAICompatibleProvider

    settings = get_settings()
    provider = OpenAICompatibleProvider()
    return OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        base_url=provider._api_base(settings, purpose="embedding"),
        api_key=provider._api_key(settings, purpose="embedding") or "x",
        check_embedding_ctx_length=False,
    )


def _answer(chat, question: str, contexts: list[str]) -> str:
    context_text = "\n\n".join(f"[{index}] {text}" for index, text in enumerate(contexts, start=1))
    response = chat.invoke(
        [
            {
                "role": "system",
                "content": "仅根据给定知识库片段回答问题；证据不足时明确说明不知道。回答保持简洁。",
            },
            {"role": "user", "content": f"知识库片段：\n{context_text}\n\n问题：{question}"},
        ]
    )
    content = response.content
    if isinstance(content, str):
        return content.strip()
    return json.dumps(content, ensure_ascii=False)


def _cleanup_temp_data(db, temp_state: dict) -> None:
    kb = temp_state.get("kb")
    if kb is None:
        return
    from core.db.models import KnowledgeBase
    from core.integrations import vector_store as vector_store_module

    try:
        vector_store_module.vector_store.delete(
            filters={"workspace_id": kb.workspace_id, "knowledge_base_id": kb.id}
        )
    finally:
        db.query(KnowledgeBase).filter(KnowledgeBase.id == kb.id).delete(synchronize_session=False)
        db.commit()


def run_live(cases_path: Path, limit: int) -> dict:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=DeprecationWarning,
            message=r"Importing .* from 'ragas\.metrics'.*",
        )
        from ragas import EvaluationDataset, evaluate
        from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference, ResponseRelevancy
    from ragas.run_config import RunConfig

    from core.config import get_settings
    from core.db.session import SessionLocal
    from core.integrations import vector_store as vector_store_module
    from core.integrations.langchain_provider import get_chat_model
    from core.services import rag

    settings = get_settings()
    vector_status = vector_store_module.vector_store.status()
    if vector_status.get("active_backend") != "milvus":
        raise RuntimeError(f"--live requires active Milvus, got: {vector_status}")

    selected, skipped = _eligible_cases(load_cases(cases_path), limit)
    if not selected:
        raise RuntimeError("no eligible non-refusal RAG cases")

    db = SessionLocal()
    temp_state: dict = {}
    samples = []
    metadata = []
    chat = get_chat_model(temperature=0.0)
    try:
        for case in selected:
            target = _find_case_target(db, case)
            if target is None:
                target = _ensure_temp_target(db, case, temp_state)
            workspace_id, kb_id = int(target[0]), int(target[1])
            result = rag.retrieve(
                db,
                workspace_id=workspace_id,
                knowledge_base_ids=[kb_id],
                query=case["question"],
                config={
                    "top_k": settings.rag_top_k,
                    "dense_top_k": settings.rag_dense_top_k,
                    "bm25_top_k": settings.rag_bm25_top_k,
                    "rrf_k": settings.rag_rrf_k,
                    "rerank_enabled": False,
                    "cache_enabled": False,
                    "parent_expansion": settings.rag_parent_expansion,
                },
            )
            contexts = [
                str(source.get("content") or source.get("snippet") or "").strip()
                for source in result.sources
                if str(source.get("content") or source.get("snippet") or "").strip()
            ]
            if not contexts:
                raise RuntimeError(f"case {case.get('id')} retrieved no contexts")
            answer = _answer(chat, case["question"], contexts)
            samples.append(
                {
                    "user_input": case["question"],
                    "response": answer,
                    "retrieved_contexts": contexts,
                }
            )
            metadata.append(
                {
                    "id": case.get("id"),
                    "question": case["question"],
                    "answer": answer,
                    "contexts": len(contexts),
                }
            )

        dataset = EvaluationDataset.from_list(samples)
        metrics = [
            Faithfulness(),
            ResponseRelevancy(strictness=1),
            LLMContextPrecisionWithoutReference(),
        ]
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, message=r"evaluate\(\) is deprecated.*")
            evaluation = evaluate(
                dataset,
                metrics=metrics,
                llm=chat,
                embeddings=_embedding_model(),
                run_config=RunConfig(timeout=120, max_retries=1, max_workers=1),
                raise_exceptions=True,
                show_progress=False,
            )
        score_rows = []
        for case_meta, scores in zip(metadata, evaluation.scores):
            normalized_scores = {
                key: round(float(value), 4) if value is not None and math.isfinite(float(value)) else None
                for key, value in scores.items()
            }
            score_rows.append({**case_meta, "scores": normalized_scores})
        metric_names = ["faithfulness", "answer_relevancy", "llm_context_precision_without_reference"]
        summary = {}
        for name in metric_names:
            values = [row["scores"].get(name) for row in score_rows]
            values = [value for value in values if value is not None]
            summary[name] = round(sum(values) / len(values), 4) if values else None
        return {
            "ragas_version": version("ragas"),
            "active_vector_backend": vector_status["active_backend"],
            "cases": score_rows,
            "summary": summary,
            "skipped": skipped,
        }
    finally:
        try:
            _cleanup_temp_data(db, temp_state)
        finally:
            db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline Ragas evaluation against live RAG infrastructure.")
    parser.add_argument("--live", action="store_true", help="Allow real model, database, and Milvus calls.")
    parser.add_argument("--cases", default="eval/rag_cases.jsonl")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    if not args.live:
        raise SystemExit("Refusing to run without --live; this script performs real model and infrastructure calls.")
    output = run_live(Path(args.cases), max(1, args.limit))
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
