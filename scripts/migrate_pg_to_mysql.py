"""PostgreSQL → MySQL 数据迁移脚本。"""
import json as _json
from sqlalchemy import create_engine, inspect, text

PG_URL = "postgresql://lingshu:lingshu@192.168.150.101:5433/lingshu_agent"
MY_URL = "mysql+pymysql://lingshu:lingshu@192.168.150.101:3306/lingshu_agent"

TABLES = [
    "users", "workspaces", "model_configs",
    "workspace_members", "workspace_invites",
    "user_model_configs",
    "agents", "agent_versions", "agent_settings",
    "tools", "agent_tools",
    "knowledge_bases", "agent_knowledge_bases",
    "knowledge_documents", "knowledge_chunks",
    "workflow_definitions", "prompt_templates",
    "sessions", "messages", "runs", "run_steps",
    "session_memory", "agent_memory_profiles",
    "feedback", "uploads",
]

# MySQL 列默认值 / NULL 替换
COLUMN_DEFAULTS = {
    "query_understanding": "{}",
    "is_debug": False,
    "method": "",       # PG 内置工具有 NULL method，MySQL 定义为 NOT NULL
    "url": "",          # 同上
    "auth_header_name": "",  # 同上
    "auth_query_name": "",   # 同上
    "encrypted_secret": "",  # 同上
}
# PG NULL → 替换为以下类型的默认空值
NULL_REPLACEMENTS = {
    str: "",
    int: 0,
    bool: False,
}

pg = create_engine(PG_URL, future=True)
my = create_engine(MY_URL, future=True)
pgi = inspect(pg)
myi = inspect(my)

# 清空 MySQL 现有数据
with my.connect() as conn:
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    for table in reversed(TABLES):
        try:
            conn.execute(text(f"DELETE FROM {table}"))
        except Exception:
            pass  # 表可能为空
    conn.commit()
    print("Cleared existing MySQL data.\n")

# 迁移
total = 0
for table in TABLES:
    pg_cols = {c["name"] for c in pgi.get_columns(table)}
    my_cols_all = myi.get_columns(table)
    my_cols = {c["name"] for c in my_cols_all}
    my_col_info = {c["name"]: c for c in my_cols_all}

    # 用 MySQL 列作为目标（PG 有的就取值，没有的用默认值），跳过触发器维护列
    SKIP_COLS = {"is_default_ukey", "global_name_ukey", "owner_name_ukey"}
    target_cols = sorted(my_cols - SKIP_COLS)
    if not target_cols:
        print(f"  {table}: SKIP")
        continue

    # PG 中存在的列
    pg_available = sorted(pg_cols & set(target_cols))

    with pg.connect() as pg_conn:
        pg_rows = pg_conn.execute(
            text(f'SELECT {", ".join(pg_available)} FROM {table}')
        ).fetchall()

    if not pg_rows:
        print(f"  {table}: 0 rows (PG empty)")
        continue

    placeholders = ", ".join([f":{c}" for c in target_cols])
    cols_str = ", ".join(f"`{c}`" for c in target_cols)
    sql = text(f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})")

    with my.begin() as conn:
        for row in pg_rows:
            params = {}
            for col in target_cols:
                if col in pg_cols:
                    val = getattr(row, col)
                    # 处理 PG NULL 值：MySQL NOT NULL 列需要默认值
                    if val is None:
                        val = COLUMN_DEFAULTS.get(col)
                        if val is None and not my_col_info[col]["nullable"]:
                            # 根据 MySQL 列类型给空默认值
                            col_type = str(my_col_info[col]["type"]).upper()
                            if "INT" in col_type:
                                val = 0
                            elif "CHAR" in col_type or "TEXT" in col_type:
                                val = ""
                            elif "BOOL" in col_type:
                                val = False
                            elif "FLOAT" in col_type or "DOUBLE" in col_type:
                                val = 0.0
                else:
                    # PG 没有该列，用默认值
                    val = COLUMN_DEFAULTS.get(col)
                    if val is None and my_col_info[col]["nullable"]:
                        val = None

                if isinstance(val, (dict, list)):
                    val = _json.dumps(val)
                params[col] = val
            conn.execute(sql, params)

    print(f"  {table}: {len(pg_rows)} rows")
    total += len(pg_rows)

# 恢复 FK 检查
with my.connect() as conn:
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    conn.commit()

pg.dispose()
my.dispose()

print(f"\nDone. {total} rows migrated.")
