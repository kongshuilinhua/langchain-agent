-- Lingshu Agent complete MySQL schema.
-- Converted from sql/postgresql/001_init_schema.sql.
-- Target runtime: MySQL 8.0 from docker-compose.yml.

-- Key conversions:
--   BIGSERIAL      → BIGINT AUTO_INCREMENT
--   JSONB          → JSON
--   TIMESTAMPTZ    → TIMESTAMP
--   DOUBLE PRECISION → DOUBLE
--   ON CONFLICT    → ON DUPLICATE KEY UPDATE
--   Partial unique indexes → generated columns + unique indexes (MySQL ignores NULLs)
--   PL/pgSQL trigger function → individual BEFORE UPDATE triggers

CREATE TABLE IF NOT EXISTS users (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    avatar_url TEXT NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_users_email ON users (email);

CREATE TABLE IF NOT EXISTS workspaces (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    slug VARCHAR(160) NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_workspaces_slug ON workspaces (slug);

CREATE TABLE IF NOT EXISTS workspace_members (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    role VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_workspace_member UNIQUE (workspace_id, user_id),
    CONSTRAINT fk_workspace_members_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    CONSTRAINT fk_workspace_members_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX ix_workspace_members_workspace_id ON workspace_members (workspace_id);
CREATE INDEX ix_workspace_members_user_id ON workspace_members (user_id);

CREATE TABLE IF NOT EXISTS workspace_invites (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    email VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL,
    token VARCHAR(80) NOT NULL UNIQUE,
    accepted_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_workspace_invites_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);
CREATE INDEX ix_workspace_invites_workspace_id ON workspace_invites (workspace_id);
CREATE INDEX ix_workspace_invites_token ON workspace_invites (token);

CREATE TABLE IF NOT EXISTS model_configs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    provider VARCHAR(80) NOT NULL DEFAULT 'openai-compatible',
    model_name VARCHAR(160) NOT NULL UNIQUE,
    display_name VARCHAR(160) NOT NULL,
    supports_text BOOLEAN NOT NULL DEFAULT TRUE,
    supports_image BOOLEAN NOT NULL DEFAULT FALSE,
    supports_document BOOLEAN NOT NULL DEFAULT TRUE,
    supports_reasoning BOOLEAN NOT NULL DEFAULT FALSE,
    reasoning_type VARCHAR(20) NOT NULL DEFAULT 'none',
    reasoning_label VARCHAR(80) NOT NULL DEFAULT '不支持',
    max_context INTEGER NOT NULL DEFAULT 8192,
    default_temperature DOUBLE NOT NULL DEFAULT 0.4,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_model_configs_model_name ON model_configs (model_name);
CREATE INDEX ix_model_configs_enabled ON model_configs (enabled);

CREATE TABLE IF NOT EXISTS user_model_configs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    display_name VARCHAR(160) NOT NULL,
    provider VARCHAR(80) NOT NULL DEFAULT 'openai-compatible',
    base_url VARCHAR(500) NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    chat_model VARCHAR(160) NOT NULL,
    supports_image BOOLEAN NOT NULL DEFAULT FALSE,
    supports_document BOOLEAN NOT NULL DEFAULT TRUE,
    supports_reasoning BOOLEAN NOT NULL DEFAULT FALSE,
    reasoning_type VARCHAR(20) NOT NULL DEFAULT 'none',
    reasoning_label VARCHAR(80) NOT NULL DEFAULT '不支持',
    max_context INTEGER NOT NULL DEFAULT 131072,
    default_temperature DOUBLE NOT NULL DEFAULT 0.4,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_model_configs_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX ix_user_model_configs_user_id ON user_model_configs (user_id);
CREATE INDEX ix_user_model_configs_enabled ON user_model_configs (user_id, enabled);

-- Partial unique index: one default per user.
-- MySQL workaround: regular column + triggers + unique index.
-- NULL values are ignored in MySQL unique indexes, so only is_default=1 rows conflict.
ALTER TABLE user_model_configs ADD COLUMN is_default_ukey VARCHAR(64) NULL;
CREATE UNIQUE INDEX uq_one_default_per_user ON user_model_configs (is_default_ukey);
CREATE TRIGGER trg_umc_default_ins
BEFORE INSERT ON user_model_configs FOR EACH ROW
SET NEW.is_default_ukey = IF(NEW.is_default = 1, CAST(NEW.user_id AS CHAR(64)), NULL);
CREATE TRIGGER trg_umc_default_upd
BEFORE UPDATE ON user_model_configs FOR EACH ROW
SET NEW.is_default_ukey = IF(NEW.is_default = 1, CAST(NEW.user_id AS CHAR(64)), NULL);

CREATE TABLE IF NOT EXISTS agents (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    model_id BIGINT NULL,
    user_model_config_id BIGINT NULL,
    name VARCHAR(160) NOT NULL,
    avatar VARCHAR(40) NOT NULL DEFAULT 'SA',
    description TEXT NOT NULL,
    opening_message TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    model VARCHAR(120) NOT NULL DEFAULT 'qwen-plus',
    temperature DOUBLE NOT NULL DEFAULT 0.4,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    published_version_id BIGINT NULL,
    is_template BOOLEAN NOT NULL DEFAULT FALSE,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_agents_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    CONSTRAINT fk_agents_model FOREIGN KEY (model_id) REFERENCES model_configs(id) ON DELETE SET NULL,
    CONSTRAINT fk_agents_user_model FOREIGN KEY (user_model_config_id) REFERENCES user_model_configs(id) ON DELETE SET NULL,
    CONSTRAINT fk_agents_created_by FOREIGN KEY (created_by) REFERENCES users(id)
);
CREATE INDEX ix_agents_workspace_id ON agents (workspace_id);
CREATE INDEX ix_agents_model_id ON agents (model_id);
CREATE INDEX ix_agents_user_model_config_id ON agents (user_model_config_id);
CREATE INDEX ix_agents_created_by ON agents (created_by);
CREATE INDEX ix_agents_status ON agents (workspace_id, status);
CREATE INDEX ix_agents_published_version_id ON agents (published_version_id);

CREATE TABLE IF NOT EXISTS agent_versions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_id BIGINT NOT NULL,
    version INTEGER NOT NULL,
    snapshot JSON NOT NULL,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_versions_version UNIQUE (agent_id, version),
    CONSTRAINT fk_agent_versions_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_versions_created_by FOREIGN KEY (created_by) REFERENCES users(id)
);
CREATE INDEX ix_agent_versions_agent_id ON agent_versions (agent_id);
CREATE INDEX ix_agent_versions_created_by ON agent_versions (created_by);

-- Foreign key from agents.published_version_id to agent_versions.id.
-- MySQL: add unconditionally (table is created above, so no need for conditional DO $$ block).
ALTER TABLE agents
ADD CONSTRAINT fk_agents_published_version
FOREIGN KEY (published_version_id) REFERENCES agent_versions(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS agent_settings (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_id BIGINT NOT NULL UNIQUE,
    suggested_questions JSON NOT NULL,
    variables JSON NOT NULL,
    memory JSON NOT NULL,
    rag JSON NOT NULL,
    tool_policy JSON NOT NULL,
    query_understanding JSON NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_agent_settings_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX ix_agent_settings_agent_id ON agent_settings (agent_id);

CREATE TABLE IF NOT EXISTS tools (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    workspace_id BIGINT NULL,
    user_id BIGINT NULL,
    type VARCHAR(40) NOT NULL DEFAULT 'builtin',
    name VARCHAR(120) NOT NULL,
    label VARCHAR(160) NOT NULL,
    description TEXT NOT NULL,
    schema JSON NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    method VARCHAR(10) NULL,
    url TEXT NULL,
    headers_schema JSON NOT NULL,
    query_schema JSON NOT NULL,
    body_schema JSON NOT NULL,
    auth_type VARCHAR(40) NOT NULL DEFAULT 'none',
    auth_header_name VARCHAR(120) NULL,
    auth_query_name VARCHAR(120) NULL,
    encrypted_secret TEXT NULL,
    response_path VARCHAR(255) NOT NULL DEFAULT '$',
    timeout_seconds INTEGER NOT NULL DEFAULT 10,
    search_options JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_tools_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    CONSTRAINT fk_tools_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Partial unique index: global tools (workspace_id IS NULL AND user_id IS NULL) have unique names.
-- MySQL workaround: regular column + triggers + unique index.
ALTER TABLE tools ADD COLUMN global_name_ukey VARCHAR(200) NULL;
CREATE UNIQUE INDEX uq_tools_global_name ON tools (global_name_ukey);
CREATE TRIGGER trg_tools_global_name_ins
BEFORE INSERT ON tools FOR EACH ROW
SET NEW.global_name_ukey = IF(NEW.workspace_id IS NULL AND NEW.user_id IS NULL, NEW.name, NULL);
CREATE TRIGGER trg_tools_global_name_upd
BEFORE UPDATE ON tools FOR EACH ROW
SET NEW.global_name_ukey = IF(NEW.workspace_id IS NULL AND NEW.user_id IS NULL, NEW.name, NULL);

-- Partial unique index: workspace/user tools have unique names within their scope.
ALTER TABLE tools ADD COLUMN owner_name_ukey VARCHAR(400) NULL;
CREATE UNIQUE INDEX uq_tools_owner_name ON tools (owner_name_ukey);
CREATE TRIGGER trg_tools_owner_name_ins
BEFORE INSERT ON tools FOR EACH ROW
SET NEW.owner_name_ukey = IF(NEW.workspace_id IS NOT NULL AND NEW.user_id IS NOT NULL,
    CONCAT(NEW.workspace_id, ':', NEW.user_id, ':', NEW.name), NULL);
CREATE TRIGGER trg_tools_owner_name_upd
BEFORE UPDATE ON tools FOR EACH ROW
SET NEW.owner_name_ukey = IF(NEW.workspace_id IS NOT NULL AND NEW.user_id IS NOT NULL,
    CONCAT(NEW.workspace_id, ':', NEW.user_id, ':', NEW.name), NULL);

CREATE INDEX ix_tools_workspace_id ON tools (workspace_id);
CREATE INDEX ix_tools_user_id ON tools (user_id);
CREATE INDEX ix_tools_type ON tools (type);
CREATE INDEX ix_tools_enabled ON tools (enabled);
CREATE INDEX ix_tools_name ON tools (name);

CREATE TABLE IF NOT EXISTS agent_tools (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_id BIGINT NOT NULL,
    tool_id BIGINT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    config JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_tool UNIQUE (agent_id, tool_id),
    CONSTRAINT fk_agent_tools_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_tools_tool FOREIGN KEY (tool_id) REFERENCES tools(id) ON DELETE CASCADE
);
CREATE INDEX ix_agent_tools_agent_id ON agent_tools (agent_id);
CREATE INDEX ix_agent_tools_tool_id ON agent_tools (tool_id);
CREATE INDEX ix_agent_tools_enabled ON agent_tools (enabled);

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    name VARCHAR(160) NOT NULL,
    description TEXT NOT NULL,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_knowledge_bases_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    CONSTRAINT fk_knowledge_bases_created_by FOREIGN KEY (created_by) REFERENCES users(id)
);
CREATE INDEX ix_knowledge_bases_workspace_id ON knowledge_bases (workspace_id);
CREATE INDEX ix_knowledge_bases_created_by ON knowledge_bases (created_by);

CREATE TABLE IF NOT EXISTS agent_knowledge_bases (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_id BIGINT NOT NULL,
    knowledge_base_id BIGINT NOT NULL,
    CONSTRAINT uq_agent_kb UNIQUE (agent_id, knowledge_base_id),
    CONSTRAINT fk_agent_knowledge_bases_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_knowledge_bases_kb FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);
CREATE INDEX ix_agent_knowledge_bases_agent_id ON agent_knowledge_bases (agent_id);
CREATE INDEX ix_agent_knowledge_bases_knowledge_base_id ON agent_knowledge_bases (knowledge_base_id);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    knowledge_base_id BIGINT NOT NULL,
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(120) NOT NULL,
    source_type VARCHAR(40) NOT NULL DEFAULT 'text',
    text LONGTEXT NOT NULL,
    text_preview TEXT NOT NULL,
    title VARCHAR(255) NOT NULL DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'uploaded',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NOT NULL,
    segment_config JSON,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_knowledge_documents_kb FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
);
CREATE INDEX ix_knowledge_documents_knowledge_base_id ON knowledge_documents (knowledge_base_id);
CREATE INDEX ix_knowledge_documents_status ON knowledge_documents (status);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    knowledge_base_id BIGINT NOT NULL,
    document_id BIGINT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text LONGTEXT NOT NULL,
    vector_id VARCHAR(120) NOT NULL UNIQUE,
    parent_id VARCHAR(120) NOT NULL DEFAULT '',
    chunk_id VARCHAR(120) NOT NULL DEFAULT '',
    title VARCHAR(255) NOT NULL DEFAULT '',
    page INTEGER,
    section VARCHAR(255) NOT NULL DEFAULT '',
    content_hash VARCHAR(80) NOT NULL DEFAULT '',
    embedding_model VARCHAR(160) NOT NULL DEFAULT '',
    embedding_dimension INTEGER NOT NULL DEFAULT 0,
    metadata JSON NOT NULL,
    CONSTRAINT fk_knowledge_chunks_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    CONSTRAINT fk_knowledge_chunks_kb FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    CONSTRAINT fk_knowledge_chunks_document FOREIGN KEY (document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
);
CREATE INDEX ix_knowledge_chunks_workspace_id ON knowledge_chunks (workspace_id);
CREATE INDEX ix_knowledge_chunks_knowledge_base_id ON knowledge_chunks (knowledge_base_id);
CREATE INDEX ix_knowledge_chunks_document_id ON knowledge_chunks (document_id);
CREATE INDEX ix_knowledge_chunks_vector_id ON knowledge_chunks (vector_id);
CREATE INDEX ix_knowledge_chunks_parent_id ON knowledge_chunks (parent_id);
CREATE INDEX ix_knowledge_chunks_chunk_id ON knowledge_chunks (chunk_id);
CREATE INDEX ix_knowledge_chunks_content_hash ON knowledge_chunks (content_hash);

CREATE TABLE IF NOT EXISTS workflow_definitions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    agent_id BIGINT NOT NULL UNIQUE,
    nodes JSON NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_workflow_definitions_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX ix_workflow_definitions_agent_id ON workflow_definitions (agent_id);

CREATE TABLE IF NOT EXISTS uploads (
    id VARCHAR(80) PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(120) NOT NULL,
    kind VARCHAR(30) NOT NULL,
    data_url TEXT NOT NULL,
    text LONGTEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_uploads_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    CONSTRAINT fk_uploads_user FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX ix_uploads_workspace_id ON uploads (workspace_id);
CREATE INDEX ix_uploads_user_id ON uploads (user_id);
CREATE INDEX ix_uploads_kind ON uploads (kind);

CREATE TABLE IF NOT EXISTS sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    agent_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    title VARCHAR(200) NOT NULL DEFAULT 'New conversation',
    is_debug BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_sessions_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    CONSTRAINT fk_sessions_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX ix_sessions_workspace_id ON sessions (workspace_id);
CREATE INDEX ix_sessions_agent_id ON sessions (agent_id);
CREATE INDEX ix_sessions_user_id ON sessions (user_id);
CREATE INDEX ix_sessions_agent_user_updated ON sessions (agent_id, user_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id BIGINT NOT NULL,
    role VARCHAR(20) NOT NULL,
    content LONGTEXT NOT NULL,
    sources JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_messages_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX ix_messages_session_id ON messages (session_id);
CREATE INDEX ix_messages_role ON messages (role);
CREATE INDEX ix_messages_created_at ON messages (created_at);

CREATE TABLE IF NOT EXISTS runs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    agent_id BIGINT NOT NULL,
    session_id BIGINT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    CONSTRAINT fk_runs_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    CONSTRAINT fk_runs_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    CONSTRAINT fk_runs_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX ix_runs_workspace_id ON runs (workspace_id);
CREATE INDEX ix_runs_agent_id ON runs (agent_id);
CREATE INDEX ix_runs_session_id ON runs (session_id);
CREATE INDEX ix_runs_status ON runs (status);

CREATE TABLE IF NOT EXISTS run_steps (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    run_id BIGINT NOT NULL,
    node_id VARCHAR(80) NOT NULL,
    node_type VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL,
    input JSON NOT NULL,
    output JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_run_steps_run FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX ix_run_steps_run_id ON run_steps (run_id);
CREATE INDEX ix_run_steps_status ON run_steps (status);
CREATE INDEX ix_run_steps_node_type ON run_steps (node_type);

CREATE TABLE IF NOT EXISTS session_memory (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id BIGINT NOT NULL UNIQUE,
    summary TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_session_memory_session FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX ix_session_memory_session_id ON session_memory (session_id);

CREATE TABLE IF NOT EXISTS agent_memory_profiles (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    agent_id BIGINT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    summary TEXT NOT NULL,
    facts JSON NOT NULL,
    preferences JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_memory_profile_scope UNIQUE (workspace_id, user_id, agent_id),
    CONSTRAINT fk_agent_memory_profiles_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_memory_profiles_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_memory_profiles_agent FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
CREATE INDEX ix_agent_memory_profiles_workspace_id ON agent_memory_profiles (workspace_id);
CREATE INDEX ix_agent_memory_profiles_user_id ON agent_memory_profiles (user_id);
CREATE INDEX ix_agent_memory_profiles_agent_id ON agent_memory_profiles (agent_id);
CREATE INDEX ix_agent_memory_profiles_enabled ON agent_memory_profiles (enabled);

CREATE TABLE IF NOT EXISTS prompt_templates (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    workspace_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    title VARCHAR(160) NOT NULL,
    description TEXT NOT NULL,
    content LONGTEXT NOT NULL,
    category VARCHAR(80) NOT NULL DEFAULT 'general',
    tags JSON NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_prompt_templates_owner_title UNIQUE (workspace_id, user_id, title),
    CONSTRAINT fk_prompt_templates_workspace FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    CONSTRAINT fk_prompt_templates_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX ix_prompt_templates_workspace_id ON prompt_templates (workspace_id);
CREATE INDEX ix_prompt_templates_user_id ON prompt_templates (user_id);
CREATE INDEX ix_prompt_templates_category ON prompt_templates (category);
CREATE INDEX ix_prompt_templates_enabled ON prompt_templates (enabled);

CREATE TABLE IF NOT EXISTS feedback (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    message_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    rating VARCHAR(20) NOT NULL,
    comment TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_feedback_message_user UNIQUE (message_id, user_id),
    CONSTRAINT fk_feedback_message FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
    CONSTRAINT fk_feedback_user FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX ix_feedback_message_id ON feedback (message_id);
CREATE INDEX ix_feedback_user_id ON feedback (user_id);

-- ── Triggers: auto-update updated_at on BEFORE UPDATE ──

CREATE TRIGGER trg_user_model_configs_updated_at
BEFORE UPDATE ON user_model_configs
FOR EACH ROW SET NEW.updated_at = NOW();

CREATE TRIGGER trg_agents_updated_at
BEFORE UPDATE ON agents
FOR EACH ROW SET NEW.updated_at = NOW();

CREATE TRIGGER trg_agent_settings_updated_at
BEFORE UPDATE ON agent_settings
FOR EACH ROW SET NEW.updated_at = NOW();

CREATE TRIGGER trg_prompt_templates_updated_at
BEFORE UPDATE ON prompt_templates
FOR EACH ROW SET NEW.updated_at = NOW();

CREATE TRIGGER trg_tools_updated_at
BEFORE UPDATE ON tools
FOR EACH ROW SET NEW.updated_at = NOW();

CREATE TRIGGER trg_knowledge_documents_updated_at
BEFORE UPDATE ON knowledge_documents
FOR EACH ROW SET NEW.updated_at = NOW();

CREATE TRIGGER trg_workflow_definitions_updated_at
BEFORE UPDATE ON workflow_definitions
FOR EACH ROW SET NEW.updated_at = NOW();

CREATE TRIGGER trg_sessions_updated_at
BEFORE UPDATE ON sessions
FOR EACH ROW SET NEW.updated_at = NOW();

CREATE TRIGGER trg_session_memory_updated_at
BEFORE UPDATE ON session_memory
FOR EACH ROW SET NEW.updated_at = NOW();

CREATE TRIGGER trg_agent_memory_profiles_updated_at
BEFORE UPDATE ON agent_memory_profiles
FOR EACH ROW SET NEW.updated_at = NOW();

-- ── Seed data ──

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
ON DUPLICATE KEY UPDATE
    provider = VALUES(provider),
    display_name = VALUES(display_name),
    supports_text = VALUES(supports_text),
    supports_image = VALUES(supports_image),
    supports_document = VALUES(supports_document),
    supports_reasoning = VALUES(supports_reasoning),
    reasoning_type = VALUES(reasoning_type),
    reasoning_label = VALUES(reasoning_label),
    max_context = VALUES(max_context),
    default_temperature = VALUES(default_temperature),
    enabled = VALUES(enabled);

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
    ('builtin', 'weather', 'Weather tool', 'Demo weather advice by city.', '{}', '{}', '{}', '{}', '{}', TRUE),
    ('builtin', 'report', 'Report tool', 'Demo device report by user id.', '{}', '{}', '{}', '{}', '{}', TRUE),
    ('builtin_search', 'web_search', 'Web search', 'Search public web pages and return short snippets.', '{}', '{}', '{}', '{}', '{"max_results": 5}', TRUE)
ON DUPLICATE KEY UPDATE
    label = VALUES(label),
    description = VALUES(description),
    enabled = VALUES(enabled);

-- Secret rules:
-- - user_model_configs.encrypted_api_key stores encrypted model keys only.
-- - tools.encrypted_secret stores encrypted tool secrets only.
-- - agent_versions.snapshot must never contain raw or encrypted model keys or tool secrets.
