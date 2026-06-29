"""Celery 应用工厂（软依赖）。

🎯 设计要点：
    - celery 未安装、或 CELERY_ENABLED=false、或未配置 broker 时，`celery_app` 为 None，
      调度层（dispatch.py）自动回退到 FastAPI BackgroundTasks，保持单机开箱即用。
    - broker / result backend 缺省复用 REDIS_URL，避免重复配置。
    - acks_late + reject_on_worker_lost：任务执行完才向 broker 确认，worker 中途崩溃的
      在途任务会被重新投递，从根上解决「进程重启丢失在途入库任务」的问题。

worker 启动：
    celery -A core.tasks.celery_app:celery_app worker -Q lingshu --loglevel=info
"""

from __future__ import annotations

import logging

from core.config import get_settings

logger = logging.getLogger(__name__)


def build_celery_app():
    """按配置构建 Celery 实例；不满足条件时返回 None（触发回退）。"""
    settings = get_settings()
    if not settings.celery_enabled:
        return None
    try:
        from celery import Celery
    except ImportError:
        logger.warning("CELERY_ENABLED=true 但未安装 celery，异步任务回退到 BackgroundTasks。")
        return None

    broker = settings.celery_broker_url or settings.redis_url
    backend = settings.celery_result_backend or settings.redis_url
    if not broker:
        logger.warning(
            "CELERY_ENABLED=true 但未配置 broker（CELERY_BROKER_URL / REDIS_URL），回退到 BackgroundTasks。"
        )
        return None

    app = Celery("lingshu", broker=broker, backend=backend)
    app.conf.update(
        task_acks_late=True,              # 执行完才 ack：worker 崩溃→在途任务重投
        task_reject_on_worker_lost=True,
        task_track_started=True,
        worker_prefetch_multiplier=1,     # 长任务（embedding/解析）公平分发，避免单 worker 囤积
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_expires=86400,
        task_default_queue="lingshu",
        task_eager_propagates=True,       # eager 测试模式下异常照常抛出，便于断言
    )
    # 导入任务模块完成注册；jobs 仅在 celery 可用时被引用，避免无 celery 环境 import 失败。
    from core.tasks import jobs  # noqa: F401

    return app


celery_app = build_celery_app()
