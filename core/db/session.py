from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from core.config import get_settings
from core.db.base import Base


settings = get_settings()
engine = create_engine(settings.database_url, future=True)


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    from core.db import models  # noqa: F401
    from core.services.bootstrap import ensure_default_models

    Base.metadata.create_all(bind=engine)
    _run_compat_migrations()
    db = SessionLocal()
    try:
        ensure_default_models(db)
    finally:
        db.close()


def _run_compat_migrations() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    table_names = set(inspector.get_table_names())
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "avatar_url" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN avatar_url TEXT DEFAULT ''"))
    if "agents" in table_names:
        agent_columns = {column["name"] for column in inspector.get_columns("agents")}
        if "model_id" not in agent_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE agents ADD COLUMN model_id INTEGER"))
        if "user_model_config_id" not in agent_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE agents ADD COLUMN user_model_config_id INTEGER"))
        agent_indexes = {index["name"] for index in inspector.get_indexes("agents")}
        if "ix_agents_user_model_config_id" not in agent_indexes:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agents_user_model_config_id ON agents (user_model_config_id)"))
        
        avatar_col = next((col for col in inspector.get_columns("agents") if col["name"] == "avatar"), None)
        if avatar_col and getattr(avatar_col["type"], "length", None) == 40:
            if engine.dialect.name == "postgresql":
                with engine.begin() as connection:
                    connection.execute(text("ALTER TABLE agents ALTER COLUMN avatar TYPE TEXT"))
    if "user_model_configs" in table_names:
        _ensure_columns(
            "user_model_configs",
            {
                "supports_reasoning": "BOOLEAN DEFAULT false",
                "reasoning_type": "VARCHAR(20) DEFAULT 'none'",
                "reasoning_label": "VARCHAR(80) DEFAULT '不支持'",
            },
        )
        config_indexes = {index["name"] for index in inspector.get_indexes("user_model_configs")}
        if engine.dialect.name == "postgresql" and "ix_user_model_configs_one_default_per_user" not in config_indexes:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_user_model_configs_one_default_per_user "
                        "ON user_model_configs (user_id) WHERE is_default = true"
                    )
                )
    if "model_configs" in table_names:
        _ensure_columns(
            "model_configs",
            {
                "supports_reasoning": "BOOLEAN DEFAULT false",
                "reasoning_type": "VARCHAR(20) DEFAULT 'none'",
                "reasoning_label": "VARCHAR(80) DEFAULT '不支持'",
            },
        )
    if "agent_settings" in table_names:
        settings_columns = {column["name"] for column in inspector.get_columns("agent_settings")}
        if "rag" not in settings_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE agent_settings ADD COLUMN rag JSON DEFAULT '{}'"))
    if "tools" in table_names:
        _ensure_columns(
            "tools",
            {
                "workspace_id": "INTEGER",
                "user_id": "INTEGER",
                "type": "VARCHAR(40) DEFAULT 'builtin'",
                "method": "VARCHAR(12) DEFAULT 'GET'",
                "url": "TEXT DEFAULT ''",
                "headers_schema": "JSON DEFAULT '{}'",
                "query_schema": "JSON DEFAULT '{}'",
                "body_schema": "JSON DEFAULT '{}'",
                "auth_type": "VARCHAR(40) DEFAULT 'none'",
                "auth_header_name": "VARCHAR(120) DEFAULT 'Authorization'",
                "auth_query_name": "VARCHAR(120) DEFAULT ''",
                "encrypted_secret": "TEXT DEFAULT ''",
                "response_path": "VARCHAR(200) DEFAULT '$'",
                "timeout_seconds": "INTEGER DEFAULT 10",
                "search_options": "JSON DEFAULT '{}'",
                "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            },
        )
        tool_indexes = {index["name"] for index in inspector.get_indexes("tools")}
        if "ix_tools_workspace_id" not in tool_indexes:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tools_workspace_id ON tools (workspace_id)"))
        if "ix_tools_user_id" not in tool_indexes:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tools_user_id ON tools (user_id)"))
        if "ix_tools_name" not in tool_indexes:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tools_name ON tools (name)"))
    if "agent_tools" in table_names:
        _ensure_columns(
            "agent_tools",
            {
                "enabled": "BOOLEAN DEFAULT true",
                "config": "JSON DEFAULT '{}'",
                "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            },
        )
    if "agent_memory_profiles" in table_names:
        _ensure_columns(
            "agent_memory_profiles",
            {
                "workspace_id": "INTEGER",
                "user_id": "INTEGER",
                "agent_id": "INTEGER",
                "enabled": "BOOLEAN DEFAULT false",
                "summary": "TEXT DEFAULT ''",
                "facts": "JSON DEFAULT '[]'",
                "preferences": "JSON DEFAULT '{}'",
                "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            },
        )
        memory_indexes = {index["name"] for index in inspector.get_indexes("agent_memory_profiles")}
        if "ix_agent_memory_profiles_workspace_id" not in memory_indexes:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_memory_profiles_workspace_id ON agent_memory_profiles (workspace_id)"))
        if "ix_agent_memory_profiles_user_id" not in memory_indexes:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_memory_profiles_user_id ON agent_memory_profiles (user_id)"))
        if "ix_agent_memory_profiles_agent_id" not in memory_indexes:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_memory_profiles_agent_id ON agent_memory_profiles (agent_id)"))
        unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("agent_memory_profiles")}
        if "uq_agent_memory_profile_scope" not in unique_constraints and "uq_agent_memory_profile_scope" not in memory_indexes:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_memory_profile_scope "
                        "ON agent_memory_profiles (workspace_id, user_id, agent_id)"
                    )
                )
    if "prompt_templates" in table_names:
        _ensure_columns(
            "prompt_templates",
            {
                "workspace_id": "INTEGER",
                "user_id": "INTEGER",
                "title": "VARCHAR(160)",
                "description": "TEXT DEFAULT ''",
                "content": "TEXT DEFAULT ''",
                "category": "VARCHAR(80) DEFAULT 'general'",
                "tags": "JSON DEFAULT '[]'",
                "enabled": "BOOLEAN DEFAULT true",
                "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            },
        )
        prompt_indexes = {index["name"] for index in inspector.get_indexes("prompt_templates")}
        if "ix_prompt_templates_workspace_id" not in prompt_indexes:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_prompt_templates_workspace_id ON prompt_templates (workspace_id)"))
        if "ix_prompt_templates_user_id" not in prompt_indexes:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_prompt_templates_user_id ON prompt_templates (user_id)"))
        if "ix_prompt_templates_category" not in prompt_indexes:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_prompt_templates_category ON prompt_templates (category)"))
        if "ix_prompt_templates_enabled" not in prompt_indexes:
            with engine.begin() as connection:
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_prompt_templates_enabled ON prompt_templates (enabled)"))
        unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("prompt_templates")}
        if "uq_prompt_templates_owner_title" not in unique_constraints and "uq_prompt_templates_owner_title" not in prompt_indexes:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_templates_owner_title "
                        "ON prompt_templates (workspace_id, user_id, title)"
                    )
                )
    if "knowledge_documents" in table_names:
        if engine.dialect.name == "postgresql":
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE knowledge_documents ALTER COLUMN content_type TYPE VARCHAR(120)"))
        _ensure_columns(
            "knowledge_documents",
            {
                "title": "VARCHAR(255) DEFAULT ''",
                "source_type": "VARCHAR(20) DEFAULT 'text'",
                "text_preview": "TEXT DEFAULT ''",
                "chunk_count": "INTEGER DEFAULT 0",
                "error_message": "TEXT DEFAULT ''",
                "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "segment_config": "JSON",
            },
        )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE knowledge_documents "
                    "SET title = filename "
                    "WHERE title IS NULL OR title = ''"
                )
            )
            connection.execute(
                text(
                    "UPDATE knowledge_documents "
                    "SET text_preview = substr(text, 1, 180) "
                    "WHERE text_preview IS NULL OR text_preview = ''"
                )
            )
            connection.execute(
                text(
                    "UPDATE knowledge_documents "
                    "SET chunk_count = ("
                    "SELECT count(*) FROM knowledge_chunks "
                    "WHERE knowledge_chunks.document_id = knowledge_documents.id"
                    ") "
                    "WHERE chunk_count IS NULL OR chunk_count = 0"
                )
            )
    if "knowledge_chunks" in table_names:
        _ensure_columns(
            "knowledge_chunks",
            {
                "parent_id": "VARCHAR(120) DEFAULT ''",
                "chunk_id": "VARCHAR(120) DEFAULT ''",
                "title": "VARCHAR(255) DEFAULT ''",
                "page": "INTEGER",
                "section": "VARCHAR(255) DEFAULT ''",
                "content_hash": "VARCHAR(80) DEFAULT ''",
                "embedding_model": "VARCHAR(160) DEFAULT ''",
                "embedding_dimension": "INTEGER DEFAULT 0",
                "metadata": "JSON DEFAULT '{}'",
            },
        )
        chunk_indexes = {index["name"] for index in inspector.get_indexes("knowledge_chunks")}
        for index_name, column_name in {
            "ix_knowledge_chunks_parent_id": "parent_id",
            "ix_knowledge_chunks_chunk_id": "chunk_id",
            "ix_knowledge_chunks_content_hash": "content_hash",
        }.items():
            if index_name not in chunk_indexes:
                with engine.begin() as connection:
                    connection.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON knowledge_chunks ({column_name})"))
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE knowledge_chunks SET chunk_id = vector_id "
                    "WHERE chunk_id IS NULL OR chunk_id = ''"
                )
            )
            connection.execute(
                text(
                    "UPDATE knowledge_chunks SET parent_id = vector_id "
                    "WHERE parent_id IS NULL OR parent_id = ''"
                )
            )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE workspaces SET name = replace(name, ' 的团队', ' 的工作台') "
                "WHERE name LIKE '% 的团队'"
            )
        )
        connection.execute(
            text(
                "UPDATE agents SET description = :new_value "
                "WHERE description = :old_value"
            ),
            {
                "old_value": "面向团队内部使用的自定义智能体。",
                "new_value": "用于个人或项目场景的自定义智能体。",
            },
        )
        connection.execute(
            text(
                "UPDATE agents SET opening_message = :new_value "
                "WHERE opening_message = :old_value"
            ),
            {
                "old_value": "你好，我是你的团队智能体。",
                "new_value": "你好，我是你的智能体。",
            },
        )
        connection.execute(
            text(
                "UPDATE agents SET system_prompt = :new_value "
                "WHERE system_prompt = :old_value"
            ),
            {
                "old_value": "你是一个谨慎、清晰的团队智能体。优先使用绑定知识库和工具输出回答。",
                "new_value": "你是一个谨慎、清晰的智能体。优先使用绑定知识库和工具输出回答。",
            },
        )

    if "sessions" in table_names:
        _ensure_columns(
            "sessions",
            {
                "is_debug": "BOOLEAN DEFAULT false",
            },
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_columns(table_name: str, columns: dict[str, str]) -> None:
    existing = {column["name"] for column in inspect(engine).get_columns(table_name)}
    for column_name, ddl in columns.items():
        if column_name in existing:
            continue
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
