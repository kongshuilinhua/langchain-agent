"""Alembic 迁移运行环境。

🎯 设计要点：
    - 连接串从应用配置单例 `core.config.get_settings().database_url` 注入，
      与运行时使用同一 DATABASE_URL，杜绝迁移连错库。
    - `target_metadata = Base.metadata`；导入 `core.db.models` 确保所有 ORM 模型
      都注册进 metadata，否则 autogenerate 会误判为「要删表」。
    - `compare_type=True`：让 autogenerate 能识别列类型变更（如 TEXT→LONGTEXT）。
"""

from __future__ import annotations

import logging.config

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.config import get_settings
from core.db.base import Base
import core.db.models  # noqa: F401  # 触发模型注册到 Base.metadata

config = context.config

if config.config_file_name is not None:
    logging.config.fileConfig(config.config_file_name)

# 用应用配置覆盖 ini 里留空的 sqlalchemy.url
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：仅根据 URL 渲染 SQL（`alembic upgrade --sql`），不实际连库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连库执行迁移。使用 NullPool，迁移进程不需要长连接池。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
