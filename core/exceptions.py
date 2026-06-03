"""
灵枢 Agent 平台 —— 统一异常层次体系。

🎯 架构角色：
    本模块是平台所有异常的单一来源（Single Source of Truth）。
    参考 Ragent (nageoffer/ragent) 的 AbstractException + IErrorCode 三层异常体系设计：
    - ErrorCode 枚举：可机器读取的错误码 + 人类可读的默认消息
    - AppException 基类：携带 ErrorCode、可选自定义消息、HTTP 状态码
    - 子类异常：按 HTTP 语义分类（BadRequest/Unauthorized/Forbidden/NotFound/...）

    在整个请求链路中，异常体系处于最外层的防御圈：
    业务代码抛 AppException → FastAPI exception_handler 拦截 → 统一 JSON 响应格式

    与 Ragent 的对齐：
    - Ragent AbstractException  → Lingshu AppException
    - Ragent IErrorCode         → Lingshu ErrorCode(Enum)
    - Ragent ClientException    → Lingshu BadRequestException(400)
    - Ragent ServiceException   → Lingshu InternalException(500)
    - Ragent RemoteException    → Lingshu ServiceUnavailableException(503)
"""

from enum import Enum


class ErrorCode(Enum):
    """
    平台统一错误码枚举。

    🎯 设计意图：
        参考 Ragent 的 IErrorCode 接口——将错误码定义为枚举而非自由字符串，
        确保：
        1. 编译时即可发现错误码拼写错误
        2. 新增错误类型必须显式声明
        3. 前端可以按 error_code 做精确的交互降级（而非对 message 做正则匹配）
    """

    # ── 通用系统异常 ──────────────────────────────────────────
    INTERNAL_ERROR = ("SYS_001", "内部服务异常")
    CONFIG_MISSING = ("SYS_002", "关键配置项缺失，请联系管理员")

    # ── 认证与授权 ──────────────────────────────────────────
    INVALID_TOKEN = ("AUTH_001", "令牌无效或已过期")
    INACTIVE_USER = ("AUTH_002", "用户已被禁用")
    PERMISSION_DENIED = ("AUTH_003", "无操作权限")
    INVALID_CREDENTIALS = ("AUTH_004", "邮箱或密码错误")
    EMAIL_REGISTERED = ("AUTH_005", "该邮箱已注册")
    INVITE_NOT_FOUND = ("AUTH_006", "邀请链接无效或已过期")

    # ── 资源不存在 ──────────────────────────────────────────
    AGENT_NOT_FOUND = ("AGENT_001", "智能体不存在")
    KB_NOT_FOUND = ("KB_001", "知识库不存在")
    DOCUMENT_NOT_FOUND = ("DOC_001", "文档不存在")
    SESSION_NOT_FOUND = ("SESSION_001", "会话不存在")
    TOOL_NOT_FOUND = ("TOOL_001", "工具不存在")
    MODEL_NOT_FOUND = ("MODEL_001", "模型不存在")
    USER_NOT_FOUND = ("USER_001", "用户不存在")
    WORKSPACE_NOT_FOUND = ("WS_001", "工作空间不存在")
    PROMPT_TEMPLATE_NOT_FOUND = ("PROMPT_001", "提示词模板不存在")
    UPLOAD_NOT_FOUND = ("UPLOAD_001", "上传文件不存在或不可访问")
    VERSION_NOT_FOUND = ("VERSION_001", "发布版本不存在")

    # ── 资源冲突 ──────────────────────────────────────────
    MODEL_DUPLICATE = ("MODEL_002", "模型名称已存在")
    TOOL_IN_USE = ("TOOL_002", "工具正在被智能体使用，无法删除")
    TEMPLATE_CANNOT_DELETE = ("AGENT_002", "系统模板智能体不可删除")

    # ── 模型与推理 ──────────────────────────────────────────
    MODEL_CALL_FAILED = ("LLM_001", "模型调用失败，请检查网络连接和 API 配置")
    MODEL_NOT_SUPPORT_DOCUMENT = ("LLM_002", "所选模型不支持文档附件，请更换模型或移除附件")
    MODEL_NOT_SUPPORT_IMAGE = ("LLM_003", "所选模型不支持图片输入")
    MODEL_EMPTY_ANSWER = ("LLM_004", "模型返回了空答案，请尝试重新提问")
    MODEL_NOT_AVAILABLE = ("LLM_005", "模型暂不可用")
    CHAT_API_KEY_MISSING = ("LLM_006", "聊天模型 API 密钥未配置")
    EMBEDDING_API_KEY_MISSING = ("LLM_007", "向量嵌入模型 API 密钥未配置")
    RERANK_API_KEY_MISSING = ("LLM_008", "重排模型 API 密钥未配置")

    # ── 知识库与 RAG ──────────────────────────────────────
    KB_INDEX_FAILED = ("KB_002", "知识库索引构建失败")
    KB_UPLOAD_FAILED = ("KB_003", "知识文档上传处理失败")
    KB_RESEARCH_FAILED = ("KB_004", "文档重新分段索引失败")
    KB_NAME_EMPTY = ("KB_005", "知识库名称不能为空")

    # ── 安全 ──────────────────────────────────────────────
    ENCRYPTION_NOT_CONFIGURED = ("SEC_001", "API 密钥加密未配置，无法存储敏感凭据")
    API_KEY_INVALID = ("SEC_002", "存储的 API 密钥无效，请重新配置")
    SSRF_BLOCKED = ("SEC_003", "请求目标地址不在允许范围内")
    INVITE_API_DISABLED = ("SEC_004", "邀请注册功能未开启")

    # ── 限流 ──────────────────────────────────────────────
    RATE_LIMITED = ("RATE_001", "请求过于频繁，请稍后重试")

    # ── 工作流与 Agent ──────────────────────────────────────
    WORKFLOW_INVALID_NODES = ("WF_001", "工作流节点配置不合法")
    WORKFLOW_MISSING_START_ANSWER = ("WF_002", "工作流必须包含 Start 和 Answer 节点")
    AGENT_NOT_PUBLISHED = ("AGENT_003", "智能体还没有发布版本")
    AGENT_REVIEW_REQUIRED = ("AGENT_004", "智能体状态不是待审核")

    # ── 参数校验 ──────────────────────────────────────────
    VALIDATION_ERROR = ("VAL_001", "请求参数不正确")
    AVATAR_INVALID = ("VAL_002", "头像格式不正确，仅支持 PNG/JPG/WebP/GIF")
    PASSWORD_TOO_SHORT = ("VAL_003", "密码长度至少为 8 位")
    INVITE_ROLE_INVALID = ("VAL_004", "邀请角色只能为 user")

    @property
    def code(self) -> str:
        """返回机器可读的错误码字符串，如 'AUTH_001'。"""
        return self.value[0]

    @property
    def default_message(self) -> str:
        """返回人类可读的默认错误描述。"""
        return self.value[1]


class AppException(Exception):
    """
    平台统一异常基类。

    🎯 设计意图：
        参考 Ragent AbstractException 设计。
        每个 AppException 实例携带：
        - error_code: ErrorCode 枚举成员，提供机器可读的错误标识
        - message: 人类可读的错误描述（可选，未提供时回退到 ErrorCode 默认消息）
        - status_code: HTTP 状态码，供 FastAPI exception_handler 使用

    🛡️ 与旧代码的兼容性：
        原来的代码大量使用 HTTPException(status_code=..., detail=...) 和 ValueError。
        迁移策略：
        1. HTTPException(401, "Invalid bearer token") → UnauthorizedException(ErrorCode.INVALID_TOKEN)
        2. HTTPException(404, "Agent not found") → NotFoundException(ErrorCode.AGENT_NOT_FOUND)
        3. ValueError("...") → BadRequestException(ErrorCode.VALIDATION_ERROR, message="...")
        4. RuntimeError("Model call failed") → ServiceUnavailableException(ErrorCode.MODEL_CALL_FAILED, message="...")
    """

    def __init__(
        self,
        error_code: ErrorCode,
        message: str | None = None,
        status_code: int = 500,
    ):
        self.error_code = error_code
        self.message = message or error_code.default_message
        self.status_code = status_code
        super().__init__(self.message)


# ═══════════════════════════════════════════════════════════════
# HTTP 状态码语义化子类
# ═══════════════════════════════════════════════════════════════


class BadRequestException(AppException):
    """400 Bad Request —— 客户端请求参数有误。"""

    def __init__(self, error_code: ErrorCode = ErrorCode.VALIDATION_ERROR, message: str | None = None):
        super().__init__(error_code, message, status_code=400)


class UnauthorizedException(AppException):
    """401 Unauthorized —— 认证凭证缺失/无效/过期。"""

    def __init__(self, error_code: ErrorCode = ErrorCode.INVALID_TOKEN, message: str | None = None):
        super().__init__(error_code, message, status_code=401)


class ForbiddenException(AppException):
    """403 Forbidden —— 认证通过但无访问权限。"""

    def __init__(self, error_code: ErrorCode = ErrorCode.PERMISSION_DENIED, message: str | None = None):
        super().__init__(error_code, message, status_code=403)


class NotFoundException(AppException):
    """404 Not Found —— 请求的资源不存在。"""

    def __init__(self, error_code: ErrorCode = ErrorCode.AGENT_NOT_FOUND, message: str | None = None):
        super().__init__(error_code, message, status_code=404)


class ConflictException(AppException):
    """409 Conflict —— 资源冲突（如重复创建）。"""

    def __init__(self, error_code: ErrorCode, message: str | None = None):
        super().__init__(error_code, message, status_code=409)


class UnprocessableException(AppException):
    """422 Unprocessable Entity —— 参数合法但业务逻辑上无法处理。"""

    def __init__(self, error_code: ErrorCode, message: str | None = None):
        super().__init__(error_code, message, status_code=422)


class ServiceUnavailableException(AppException):
    """503 Service Unavailable —— 下游服务不可用（如模型 API 熔断/超时）。"""

    def __init__(self, error_code: ErrorCode = ErrorCode.INTERNAL_ERROR, message: str | None = None):
        super().__init__(error_code, message, status_code=503)
