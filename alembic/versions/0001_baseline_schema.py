"""baseline schema —— 在既有库上接管 Alembic 的基线

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-27

🎯 用途：
    把当前 ORM 模型（Base.metadata）整体作为基线。
    - 全新空库：`alembic upgrade head` 一次性按 metadata 建出全部表/索引/约束；
    - 已有库（生产环境，历史上由 init_db 的 create_all 建表）：执行 `alembic stamp head`
      只写入版本记录、不重复建表（零风险接管）。

🧠 为什么基线用 create_all 而非展开的 op.create_table：
    create_all 在运行时按真实方言渲染，能正确处理模型里的 `LongText.with_variant(LONGTEXT,"mysql")`
    等方言差异；手写 op.create_table 容易在 MySQL/PG 之间漏掉变体。

⚠️ 尚未并入 Alembic 的部分（继续由 core/db/session.py 的 _run_compat_migrations 处理）：
    - MySQL 触发器型「部分唯一索引」（user_model_configs/tools 的 *_ukey）；
    - uploads.data_url / uploads.text 的 MEDIUMTEXT 加宽；
    - 历史数据回填 UPDATE。
    这些后续应拆成独立 autogenerate/手写 revision 收编；本基线只负责把表结构纳入版本管理。
    今后所有「改表」一律走 `alembic revision --autogenerate -m "xxx"`。
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from core.db.base import Base
import core.db.models  # noqa: F401  # 注册全部模型到 metadata

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
