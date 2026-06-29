"""异步任务统一调度层。

Celery 可用 → 投递到队列（任务持久化、worker 崩溃可重投）；否则回退 FastAPI BackgroundTasks。
调用方无需感知后端差异，只提供「队列任务名 + 回退函数 + kwargs」。
"""

from __future__ import annotations

import logging

from core.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def dispatch(background_tasks, fallback, *, task_name: str, **kwargs) -> str:
    """
    把一个异步任务投递出去。

    参数：
        background_tasks: FastAPI BackgroundTasks（回退路径用）。
        fallback: 接受相同 **kwargs 的纯函数（即各服务里的实现），保证两条路径行为一致。
        task_name: Celery 任务名（与 jobs.py 中 @shared_task(name=...) 对应）。
        **kwargs: 传给任务的关键字参数（必须 JSON 可序列化，以便跨进程投递）。

    返回 "celery" 或 "background"，便于观测与测试。
    """
    if celery_app is not None:
        celery_app.send_task(task_name, kwargs=kwargs)
        return "celery"
    background_tasks.add_task(fallback, **kwargs)
    return "background"
