"""Celery 任务注册（仅在 celery 可用时被 import）。

用 @shared_task（与具体 app 解耦）注册，避免与 celery_app 的循环导入。
任务体是薄包装：复用各服务里既有的、自管理 DB Session 的纯函数，
因此同一套逻辑在 Celery worker 与 BackgroundTasks 回退路径下行为完全一致。
"""

from __future__ import annotations

from celery import shared_task

from core.runtime.workflow import compact_session_memory_task
from core.services.knowledge import run_document_ingestion, run_kb_reindex


@shared_task(name="lingshu.ingest_document")
def ingest_document(*, document_id: int, workspace_id: int, kb_id: int) -> None:
    run_document_ingestion(document_id=document_id, workspace_id=workspace_id, kb_id=kb_id)


@shared_task(name="lingshu.reindex_kb")
def reindex_kb(*, workspace_id: int, kb_id: int, job_id: str) -> None:
    run_kb_reindex(workspace_id=workspace_id, kb_id=kb_id, job_id=job_id)


@shared_task(name="lingshu.compact_session_memory")
def compact_session_memory(
    *,
    session_id: int,
    user_message: str,
    answer: str,
    max_messages: int,
    runtime_config: dict | None = None,
) -> None:
    compact_session_memory_task(
        session_id=session_id,
        user_message=user_message,
        answer=answer,
        max_messages=max_messages,
        runtime_config=runtime_config,
    )
