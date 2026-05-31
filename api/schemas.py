from pydantic import BaseModel, EmailStr, Field


class AgentRagConfig(BaseModel):
    enabled_by_default: bool = True
    top_k: int = Field(default=4, ge=1, le=20)
    dense_top_k: int | None = Field(default=None, ge=1, le=50)
    bm25_top_k: int | None = Field(default=None, ge=1, le=50)
    rrf_k: int | None = Field(default=None, ge=1, le=200)
    rerank_enabled: bool | None = None
    rerank_top_n: int | None = Field(default=None, ge=1, le=20)
    cache_enabled: bool | None = None
    refuse_when_no_evidence: bool | None = None


class AgentVariable(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    type: str = "string"
    required: bool = False
    default_value: str | int | float | bool | None = None


class AgentMemoryConfig(BaseModel):
    enabled: bool = False
    strategy: str = "session_summary"
    max_messages: int = Field(default=12, ge=1, le=100)


class MemoryProfileUpdateRequest(BaseModel):
    enabled: bool | None = None
    summary: str | None = None
    facts: list[str] | None = None
    preferences: dict[str, object] | None = None


class AgentToolPolicy(BaseModel):
    mode: str = "auto"
    allowed_tool_names: list[str] = []


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8)
    invite_token: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar_url: str | None = Field(default=None, max_length=1_500_000)


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    avatar: str = "AI"
    description: str = ""
    opening_message: str = ""
    system_prompt: str = ""
    model_id: int | None = None
    user_model_config_id: int | None = None
    model: str | None = None
    temperature: float = 0.4
    knowledge_base_ids: list[int] = []
    tool_ids: list[int] = []
    suggested_questions: list[str] = []
    variables: list[AgentVariable] = []
    memory: AgentMemoryConfig = Field(default_factory=AgentMemoryConfig)
    rag: AgentRagConfig = Field(default_factory=AgentRagConfig)
    tool_policy: AgentToolPolicy = Field(default_factory=AgentToolPolicy)


class AgentUpdateRequest(BaseModel):
    name: str | None = None
    avatar: str | None = None
    description: str | None = None
    opening_message: str | None = None
    system_prompt: str | None = None
    model_id: int | None = None
    user_model_config_id: int | None = None
    model: str | None = None
    temperature: float | None = None
    knowledge_base_ids: list[int] | None = None
    tool_ids: list[int] | None = None
    suggested_questions: list[str] | None = None
    variables: list[AgentVariable] | None = None
    memory: AgentMemoryConfig | None = None
    rag: AgentRagConfig | None = None
    tool_policy: AgentToolPolicy | None = None


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""


class KnowledgeDocumentCreateRequest(BaseModel):
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    text: str | None = Field(default=None, min_length=1)
    content: str | None = Field(default=None, min_length=1)
    content_type: str = Field(default="text/plain", min_length=1, max_length=120)
    content_base64: str | None = Field(default=None, min_length=1)
    source_type: str = Field(default="text", pattern="^(text|file)$")


class SessionUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class WorkflowUpdateRequest(BaseModel):
    nodes: list[dict]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: int | None = None
    mode: str = "draft"
    rag_enabled: bool | None = None
    rag_options: AgentRagConfig | None = None
    thinking_enabled: bool | None = None
    search_enabled: bool | None = None
    variables: dict[str, str | int | float | bool | None] = {}
    attachments: list[dict] = []
    is_debug: bool = False


class ToolRequest(BaseModel):
    type: str = Field(default="http", pattern="^(builtin_search|http)$")
    name: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=160)
    description: str = ""
    enabled: bool = True
    method: str = "GET"
    url: str = ""
    headers_schema: dict = {}
    query_schema: dict = {}
    body_schema: dict = {}
    auth: dict = {}
    response_path: str = "$"
    timeout_seconds: int = Field(default=10, ge=1, le=30)
    search_options: dict = {}


class ToolUpdateRequest(BaseModel):
    type: str | None = Field(default=None, pattern="^(builtin_search|http)$")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    label: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    enabled: bool | None = None
    method: str | None = None
    url: str | None = None
    headers_schema: dict | None = None
    query_schema: dict | None = None
    body_schema: dict | None = None
    auth: dict | None = None
    response_path: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=30)
    search_options: dict | None = None


class ToolTestRequest(BaseModel):
    input: dict = {}
    body: dict | list | str | int | float | bool | None = None


class PromptTemplateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = ""
    content: str = Field(min_length=1)
    category: str = Field(default="general", min_length=1, max_length=80)
    tags: list[str] = []
    enabled: bool = True


class PromptTemplateUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    content: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    tags: list[str] | None = None
    enabled: bool | None = None


class PromptTemplateCopyBuiltinRequest(BaseModel):
    builtin_id: str = Field(min_length=1, max_length=120)
    title: str | None = Field(default=None, min_length=1, max_length=160)


class ModelConfigRequest(BaseModel):
    provider: str = Field(default="openai-compatible", min_length=1, max_length=80)
    model_name: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=160)
    supports_text: bool = True
    supports_image: bool = False
    supports_document: bool = True
    supports_reasoning: bool = False
    reasoning_type: str = Field(default="none", pattern="^(native|prompt|none)$")
    reasoning_label: str = Field(default="不支持", max_length=80)
    max_context: int = Field(default=8192, ge=1)
    default_temperature: float = Field(default=0.4, ge=0, le=2)
    enabled: bool = True


class ModelConfigUpdateRequest(BaseModel):
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    model_name: str | None = Field(default=None, min_length=1, max_length=160)
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    supports_text: bool | None = None
    supports_image: bool | None = None
    supports_document: bool | None = None
    supports_reasoning: bool | None = None
    reasoning_type: str | None = Field(default=None, pattern="^(native|prompt|none)$")
    reasoning_label: str | None = Field(default=None, max_length=80)
    max_context: int | None = Field(default=None, ge=1)
    default_temperature: float | None = Field(default=None, ge=0, le=2)
    enabled: bool | None = None


class UserModelConfigRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    provider: str = Field(default="openai-compatible", min_length=1, max_length=80)
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str | None = Field(max_length=4096)
    chat_model: str = Field(min_length=1, max_length=160)
    supports_image: bool = False
    supports_document: bool = True
    supports_reasoning: bool = False
    reasoning_type: str = Field(default="none", pattern="^(native|prompt|none)$")
    reasoning_label: str = Field(default="不支持", max_length=80)
    max_context: int = Field(default=131072, ge=1)
    default_temperature: float = Field(default=0.4, ge=0, le=2)
    enabled: bool = True
    is_default: bool = False


class UserModelCapabilityTestRequest(UserModelConfigRequest):
    detect_image: bool = False


class UserModelConfigUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_key: str | None = Field(default=None, max_length=4096)
    chat_model: str | None = Field(default=None, min_length=1, max_length=160)
    supports_image: bool | None = None
    supports_document: bool | None = None
    supports_reasoning: bool | None = None
    reasoning_type: str | None = Field(default=None, pattern="^(native|prompt|none)$")
    reasoning_label: str | None = Field(default=None, max_length=80)
    max_context: int | None = Field(default=None, ge=1)
    default_temperature: float | None = Field(default=None, ge=0, le=2)
    enabled: bool | None = None
    is_default: bool | None = None


class UploadCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=120)
    content_base64: str = Field(min_length=1)


class InviteCreateRequest(BaseModel):
    email: EmailStr
    role: str = "user"


class InviteAcceptRequest(BaseModel):
    token: str


class FeedbackRequest(BaseModel):
    rating: str = Field(pattern="^(positive|negative|none)$")
    comment: str = ""

# Ensure Pydantic models are fully defined (required for Pydantic 2.x)
ChatRequest.model_rebuild()
