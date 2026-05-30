-- Lingshu Agent complete PostgreSQL schema.
-- Source of truth: docs/storage-design.md, docs/api-design.md,
-- docs/product-requirements.md, and docs/agent-capability-plan.md.
--
-- Target runtime: PostgreSQL 16 from docker-compose.yml.

BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    avatar_url TEXT NOT NULL DEFAULT '',
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);

CREATE TABLE IF NOT EXISTS workspaces (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    slug VARCHAR(160) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_workspaces_slug ON workspaces (slug);

CREATE TABLE IF NOT EXISTS workspace_members (
    id BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'user')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_workspace_member UNIQUE (workspace_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_workspace_members_workspace_id ON workspace_members (workspace_id);
CREATE INDEX IF NOT EXISTS ix_workspace_members_user_id ON workspace_members (user_id);

CREATE TABLE IF NOT EXISTS workspace_invites (
    id BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'user')),
    token VARCHAR(80) NOT NULL UNIQUE,
    accepted_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_workspace_invites_workspace_id ON workspace_invites (workspace_id);
CREATE INDEX IF NOT EXISTS ix_workspace_invites_token ON workspace_invites (token);

CREATE TABLE IF NOT EXISTS model_configs (
    id BIGSERIAL PRIMARY KEY,
    provider VARCHAR(80) NOT NULL DEFAULT 'openai-compatible' CHECK (provider = 'openai-compatible'),
    model_name VARCHAR(160) NOT NULL UNIQUE,
    display_name VARCHAR(160) NOT NULL,
    supports_text BOOLEAN NOT NULL DEFAULT TRUE,
    supports_image BOOLEAN NOT NULL DEFAULT FALSE,
    supports_document BOOLEAN NOT NULL DEFAULT TRUE,
    supports_reasoning BOOLEAN NOT NULL DEFAULT FALSE,
    reasoning_type VARCHAR(20) NOT NULL DEFAULT 'none' CHECK (reasoning_type IN ('native', 'prompt', 'none')),
    reasoning_label VARCHAR(80) NOT NULL DEFAULT '不支持',
    max_context INTEGER NOT NULL DEFAULT 8192 CHECK (max_context > 0),
    default_temperature DOUBLE PRECISION NOT NULL DEFAULT 0.4 CHECK (default_temperature >= 0 AND default_temperature <= 2),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_model_configs_model_name ON model_configs (model_name);
CREATE INDEX IF NOT EXISTS ix_model_configs_enabled ON model_configs (enabled);

CREATE TABLE IF NOT EXISTS user_model_configs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    display_name VARCHAR(160) NOT NULL,
    provider VARCHAR(80) NOT NULL DEFAULT 'openai-compatible' CHECK (provider = 'openai-compatible'),
    base_url VARCHAR(500) NOT NULL CHECK (length(trim(base_url)) > 0),
    encrypted_api_key TEXT NOT NULL CHECK (length(trim(encrypted_api_key)) > 0),
    chat_model VARCHAR(160) NOT NULL CHECK (length(trim(chat_model)) > 0),
    supports_image BOOLEAN NOT NULL DEFAULT FALSE,
    supports_document BOOLEAN NOT NULL DEFAULT TRUE,
    supports_reasoning BOOLEAN NOT NULL DEFAULT FALSE,
    reasoning_type VARCHAR(20) NOT NULL DEFAULT 'none' CHECK (reasoning_type IN ('native', 'prompt', 'none')),
    reasoning_label VARCHAR(80) NOT NULL DEFAULT '不支持',
    max_context INTEGER NOT NULL DEFAULT 131072 CHECK (max_context > 0),
    default_temperature DOUBLE PRECISION NOT NULL DEFAULT 0.4 CHECK (default_temperature >= 0 AND default_temperature <= 2),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_user_model_configs_user_id ON user_model_configs (user_id);
CREATE INDEX IF NOT EXISTS ix_user_model_configs_enabled ON user_model_configs (user_id, enabled);
CREATE UNIQUE INDEX IF NOT EXISTS ix_user_model_configs_one_default_per_user
    ON user_model_configs (user_id)
    WHERE is_default = TRUE;

CREATE TABLE IF NOT EXISTS agents (
    id BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    model_id BIGINT NULL REFERENCES model_configs(id) ON DELETE SET NULL,
    user_model_config_id BIGINT NULL REFERENCES user_model_configs(id) ON DELETE SET NULL,
    name VARCHAR(160) NOT NULL,
    avatar VARCHAR(40) NOT NULL DEFAULT 'SA',
    description TEXT NOT NULL DEFAULT '',
    opening_message TEXT NOT NULL DEFAULT '',
    system_prompt TEXT NOT NULL DEFAULT '',
    model VARCHAR(120) NOT NULL DEFAULT 'qwen-plus',
    temperature DOUBLE PRECISION NOT NULL DEFAULT 0.4 CHECK (temperature >= 0 AND temperature <= 2),
    status VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'pending_review', 'published', 'rejected')),
    published_version_id BIGINT NULL,
    is_template BOOLEAN NOT NULL DEFAULT FALSE,
    created_by BIGINT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_agents_workspace_id ON agents (workspace_id);
CREATE INDEX IF NOT EXISTS ix_agents_model_id ON agents (model_id);
CREATE INDEX IF NOT EXISTS ix_agents_user_model_config_id ON agents (user_model_config_id);
CREATE INDEX IF NOT EXISTS ix_agents_created_by ON agents (created_by);
CREATE INDEX IF NOT EXISTS ix_agents_status ON agents (workspace_id, status);
CREATE INDEX IF NOT EXISTS ix_agents_published_version_id ON agents (published_version_id);

CREATE TABLE IF NOT EXISTS agent_versions (
    id BIGSERIAL PRIMARY KEY,
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version > 0),
    snapshot JSONB NOT NULL,
    created_by BIGINT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_versions_version UNIQUE (agent_id, version)
);
CREATE INDEX IF NOT EXISTS ix_agent_versions_agent_id ON agent_versions (agent_id);
CREATE INDEX IF NOT EXISTS ix_agent_versions_created_by ON agent_versions (created_by);
CREATE INDEX IF NOT EXISTS ix_agent_versions_snapshot_model_id ON agent_versions ((snapshot->>'model_id'));
CREATE INDEX IF NOT EXISTS ix_agent_versions_snapshot_user_model_config_id ON agent_versions ((snapshot->>'user_model_config_id'));

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_agents_published_version'
    ) THEN
        ALTER TABLE agents
            ADD CONSTRAINT fk_agents_published_version
            FOREIGN KEY (published_version_id) REFERENCES agent_versions(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS agent_settings (
    id BIGSERIAL PRIMARY KEY,
    agent_id BIGINT NOT NULL UNIQUE REFERENCES agents(id) ON DELETE CASCADE,
    suggested_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
    variables JSONB NOT NULL DEFAULT '[]'::jsonb,
    memory JSONB NOT NULL DEFAULT '{}'::jsonb,
    rag JSONB NOT NULL DEFAULT '{}'::jsonb,
    tool_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_agent_settings_agent_id ON agent_settings (agent_id);

CREATE TABLE IF NOT EXISTS tools (
    id BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id BIGINT NULL REFERENCES users(id) ON DELETE CASCADE,
    type VARCHAR(40) NOT NULL DEFAULT 'builtin' CHECK (type IN ('builtin', 'builtin_search', 'http')),
    name VARCHAR(120) NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]*$'),
    label VARCHAR(160) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    method VARCHAR(10) NULL CHECK (method IS NULL OR method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')),
    url TEXT NULL,
    headers_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    query_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    body_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    auth_type VARCHAR(40) NOT NULL DEFAULT 'none' CHECK (auth_type IN ('none', 'bearer', 'api_key_header', 'api_key_query')),
    auth_header_name VARCHAR(120) NULL,
    auth_query_name VARCHAR(120) NULL,
    encrypted_secret TEXT NULL,
    response_path VARCHAR(255) NOT NULL DEFAULT '$',
    timeout_seconds INTEGER NOT NULL DEFAULT 10 CHECK (timeout_seconds >= 1 AND timeout_seconds <= 30),
    search_options JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (type <> 'http' OR url LIKE 'https://%')
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tools_global_name
    ON tools (name)
    WHERE workspace_id IS NULL AND user_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_tools_owner_workspace_name
    ON tools (workspace_id, user_id, name)
    WHERE workspace_id IS NOT NULL AND user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_tools_workspace_id ON tools (workspace_id);
CREATE INDEX IF NOT EXISTS ix_tools_user_id ON tools (user_id);
CREATE INDEX IF NOT EXISTS ix_tools_type ON tools (type);
CREATE INDEX IF NOT EXISTS ix_tools_enabled ON tools (enabled);

CREATE TABLE IF NOT EXISTS agent_tools (
    id BIGSERIAL PRIMARY KEY,
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    tool_id BIGINT NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_tool UNIQUE (agent_id, tool_id)
);
CREATE INDEX IF NOT EXISTS ix_agent_tools_agent_id ON agent_tools (agent_id);
CREATE INDEX IF NOT EXISTS ix_agent_tools_tool_id ON agent_tools (tool_id);
CREATE INDEX IF NOT EXISTS ix_agent_tools_enabled ON agent_tools (enabled);

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name VARCHAR(160) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by BIGINT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_knowledge_bases_workspace_id ON knowledge_bases (workspace_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_bases_created_by ON knowledge_bases (created_by);

CREATE TABLE IF NOT EXISTS agent_knowledge_bases (
    id BIGSERIAL PRIMARY KEY,
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    knowledge_base_id BIGINT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    CONSTRAINT uq_agent_kb UNIQUE (agent_id, knowledge_base_id)
);
CREATE INDEX IF NOT EXISTS ix_agent_knowledge_bases_agent_id ON agent_knowledge_bases (agent_id);
CREATE INDEX IF NOT EXISTS ix_agent_knowledge_bases_knowledge_base_id ON agent_knowledge_bases (knowledge_base_id);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id BIGSERIAL PRIMARY KEY,
    knowledge_base_id BIGINT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(80) NOT NULL,
    source_type VARCHAR(40) NOT NULL DEFAULT 'text' CHECK (source_type IN ('text', 'file')),
    text TEXT NOT NULL,
    text_preview TEXT NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'uploaded' CHECK (status IN ('uploaded', 'indexing', 'indexed', 'failed')),
    chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    error_message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_knowledge_documents_knowledge_base_id ON knowledge_documents (knowledge_base_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_documents_status ON knowledge_documents (status);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    knowledge_base_id BIGINT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    document_id BIGINT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    text TEXT NOT NULL,
    vector_id VARCHAR(120) NOT NULL UNIQUE,
    parent_id VARCHAR(120) NOT NULL DEFAULT '',
    chunk_id VARCHAR(120) NOT NULL DEFAULT '',
    title VARCHAR(255) NOT NULL DEFAULT '',
    page INTEGER,
    section VARCHAR(255) NOT NULL DEFAULT '',
    content_hash VARCHAR(80) NOT NULL DEFAULT '',
    embedding_model VARCHAR(160) NOT NULL DEFAULT '',
    embedding_dimension INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_workspace_id ON knowledge_chunks (workspace_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_knowledge_base_id ON knowledge_chunks (knowledge_base_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_document_id ON knowledge_chunks (document_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_vector_id ON knowledge_chunks (vector_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_parent_id ON knowledge_chunks (parent_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_chunk_id ON knowledge_chunks (chunk_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_content_hash ON knowledge_chunks (content_hash);

CREATE TABLE IF NOT EXISTS workflow_definitions (
    id BIGSERIAL PRIMARY KEY,
    agent_id BIGINT NOT NULL UNIQUE REFERENCES agents(id) ON DELETE CASCADE,
    nodes JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_workflow_definitions_agent_id ON workflow_definitions (agent_id);

CREATE TABLE IF NOT EXISTS uploads (
    id VARCHAR(80) PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id),
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(120) NOT NULL,
    kind VARCHAR(30) NOT NULL CHECK (kind IN ('image', 'document')),
    data_url TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0 CHECK (size >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_uploads_workspace_id ON uploads (workspace_id);
CREATE INDEX IF NOT EXISTS ix_uploads_user_id ON uploads (user_id);
CREATE INDEX IF NOT EXISTS ix_uploads_kind ON uploads (kind);

CREATE TABLE IF NOT EXISTS sessions (
    id BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id),
    title VARCHAR(200) NOT NULL DEFAULT 'New conversation',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_sessions_workspace_id ON sessions (workspace_id);
CREATE INDEX IF NOT EXISTS ix_sessions_agent_id ON sessions (agent_id);
CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_sessions_agent_user_updated ON sessions (agent_id, user_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content TEXT NOT NULL,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_messages_session_id ON messages (session_id);
CREATE INDEX IF NOT EXISTS ix_messages_role ON messages (role);
CREATE INDEX IF NOT EXISTS ix_messages_created_at ON messages (created_at);

CREATE TABLE IF NOT EXISTS runs (
    id BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    session_id BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS ix_runs_workspace_id ON runs (workspace_id);
CREATE INDEX IF NOT EXISTS ix_runs_agent_id ON runs (agent_id);
CREATE INDEX IF NOT EXISTS ix_runs_session_id ON runs (session_id);
CREATE INDEX IF NOT EXISTS ix_runs_status ON runs (status);

CREATE TABLE IF NOT EXISTS run_steps (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    node_id VARCHAR(80) NOT NULL,
    node_type VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('started', 'running', 'succeeded', 'failed', 'blocked')),
    input JSONB NOT NULL DEFAULT '{}'::jsonb,
    output JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_run_steps_run_id ON run_steps (run_id);
CREATE INDEX IF NOT EXISTS ix_run_steps_status ON run_steps (status);
CREATE INDEX IF NOT EXISTS ix_run_steps_node_type ON run_steps (node_type);

CREATE TABLE IF NOT EXISTS session_memory (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL UNIQUE REFERENCES sessions(id) ON DELETE CASCADE,
    summary TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0 CHECK (message_count >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_session_memory_session_id ON session_memory (session_id);

CREATE TABLE IF NOT EXISTS agent_memory_profiles (
    id BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id BIGINT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    summary TEXT NOT NULL DEFAULT '' CHECK (length(summary) <= 4000),
    facts JSONB NOT NULL DEFAULT '[]'::jsonb,
    preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_memory_profile_scope UNIQUE (workspace_id, user_id, agent_id)
);
CREATE INDEX IF NOT EXISTS ix_agent_memory_profiles_workspace_id ON agent_memory_profiles (workspace_id);
CREATE INDEX IF NOT EXISTS ix_agent_memory_profiles_user_id ON agent_memory_profiles (user_id);
CREATE INDEX IF NOT EXISTS ix_agent_memory_profiles_agent_id ON agent_memory_profiles (agent_id);
CREATE INDEX IF NOT EXISTS ix_agent_memory_profiles_enabled ON agent_memory_profiles (enabled);

CREATE TABLE IF NOT EXISTS prompt_templates (
    id BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(160) NOT NULL CHECK (length(trim(title)) > 0),
    description TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL CHECK (length(trim(content)) > 0),
    category VARCHAR(80) NOT NULL DEFAULT 'general',
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_prompt_templates_owner_title UNIQUE (workspace_id, user_id, title)
);
CREATE INDEX IF NOT EXISTS ix_prompt_templates_workspace_id ON prompt_templates (workspace_id);
CREATE INDEX IF NOT EXISTS ix_prompt_templates_user_id ON prompt_templates (user_id);
CREATE INDEX IF NOT EXISTS ix_prompt_templates_category ON prompt_templates (category);
CREATE INDEX IF NOT EXISTS ix_prompt_templates_enabled ON prompt_templates (enabled);

CREATE TABLE IF NOT EXISTS feedback (
    id BIGSERIAL PRIMARY KEY,
    message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id),
    rating VARCHAR(20) NOT NULL CHECK (rating IN ('positive', 'negative', 'none')),
    comment TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_feedback_message_user UNIQUE (message_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_feedback_message_id ON feedback (message_id);
CREATE INDEX IF NOT EXISTS ix_feedback_user_id ON feedback (user_id);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_user_model_configs_updated_at ON user_model_configs;
CREATE TRIGGER trg_user_model_configs_updated_at
BEFORE UPDATE ON user_model_configs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_agents_updated_at ON agents;
CREATE TRIGGER trg_agents_updated_at
BEFORE UPDATE ON agents
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_agent_settings_updated_at ON agent_settings;
CREATE TRIGGER trg_agent_settings_updated_at
BEFORE UPDATE ON agent_settings
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_prompt_templates_updated_at ON prompt_templates;
CREATE TRIGGER trg_prompt_templates_updated_at
BEFORE UPDATE ON prompt_templates
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tools_updated_at ON tools;
CREATE TRIGGER trg_tools_updated_at
BEFORE UPDATE ON tools
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_knowledge_documents_updated_at ON knowledge_documents;
CREATE TRIGGER trg_knowledge_documents_updated_at
BEFORE UPDATE ON knowledge_documents
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_workflow_definitions_updated_at ON workflow_definitions;
CREATE TRIGGER trg_workflow_definitions_updated_at
BEFORE UPDATE ON workflow_definitions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_sessions_updated_at ON sessions;
CREATE TRIGGER trg_sessions_updated_at
BEFORE UPDATE ON sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_session_memory_updated_at ON session_memory;
CREATE TRIGGER trg_session_memory_updated_at
BEFORE UPDATE ON session_memory
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_agent_memory_profiles_updated_at ON agent_memory_profiles;
CREATE TRIGGER trg_agent_memory_profiles_updated_at
BEFORE UPDATE ON agent_memory_profiles
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO model_configs (
    provider,
    model_name,
    display_name,
    supports_text,
    supports_image,
    supports_document,
    supports_reasoning,
    reasoning_type,
    reasoning_label,
    max_context,
    default_temperature,
    enabled
)
VALUES
    ('openai-compatible', 'qwen-plus', 'Qwen Plus', TRUE, FALSE, TRUE, TRUE, 'prompt', '提示词增强', 131072, 0.4, TRUE),
    ('openai-compatible', 'qwen-vl-plus', 'Qwen VL Plus', TRUE, TRUE, TRUE, TRUE, 'prompt', '提示词增强', 32768, 0.4, TRUE)
ON CONFLICT (model_name) DO UPDATE SET
    provider = EXCLUDED.provider,
    display_name = EXCLUDED.display_name,
    supports_text = EXCLUDED.supports_text,
    supports_image = EXCLUDED.supports_image,
    supports_document = EXCLUDED.supports_document,
    supports_reasoning = EXCLUDED.supports_reasoning,
    reasoning_type = EXCLUDED.reasoning_type,
    reasoning_label = EXCLUDED.reasoning_label,
    max_context = EXCLUDED.max_context,
    default_temperature = EXCLUDED.default_temperature,
    enabled = EXCLUDED.enabled;

INSERT INTO tools (
    type,
    name,
    label,
    description,
    schema,
    headers_schema,
    query_schema,
    body_schema,
    search_options,
    enabled
)
VALUES
    ('builtin', 'weather', 'Weather tool', 'Demo weather advice by city.', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, TRUE),
    ('builtin', 'report', 'Report tool', 'Demo device report by user id.', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, TRUE),
    ('builtin_search', 'web_search', 'Web search', 'Search public web pages and return short snippets.', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{"max_results": 5}'::jsonb, TRUE)
ON CONFLICT (name) WHERE workspace_id IS NULL AND user_id IS NULL DO UPDATE SET
    label = EXCLUDED.label,
    description = EXCLUDED.description,
    enabled = EXCLUDED.enabled;

-- Secret rules:
-- - user_model_configs.encrypted_api_key stores encrypted model keys only.
-- - tools.encrypted_secret stores encrypted tool secrets only.
-- - agent_versions.snapshot must never contain raw or encrypted model keys or tool secrets.

COMMIT;

