"""
灵枢 Agent 平台 —— API 密钥加密模块。

🎯 架构角色：
    本模块负责用户第三方 API Key（如 OpenAI Key、DashScope Key）的安全存储。
    这些密钥不同于用户密码——密码只需单向哈希验证，而 API Key 必须能被还原为
    明文用于实际 API 调用。因此采用 Fernet 对称加密方案。

    在数据流中的位置：
    用户提交 API Key → encrypt_api_key() → 密文存入数据库(encrypted_api_key 字段)
    Agent 执行时 → decrypt_api_key() → 还原明文 → 注入 HTTP 请求头
"""

from cryptography.fernet import Fernet

from core.config import get_settings


def _fernet() -> Fernet:
    """
    获取 Fernet 加密器实例。

    🎯 密钥来源：
        从 API_KEY_ENCRYPTION_KEY 环境变量获取。该密钥必须是 URL-safe Base64 编码的
        32 字节随机密钥（可通过 Fernet.generate_key() 生成）。

    🛡️ 安全设计：
        - 加密密钥与 JWT Secret 独立，即使 JWT 泄漏也不影响 API Key 安全
        - 未配置时使用硬编码默认值：这是开发便利性与安全性的妥协，
          生产环境 **必须** 通过环境变量覆盖，否则所有 API Key 等同于明文存储

    ⚡ Fernet 特性：
        - AES-128-CBC 加密 + HMAC-SHA256 签名 = 同时保证机密性和完整性
        - 内置时间戳：支持 token 过期（本模块未启用 TTL 特性）
        - 密文自包含：加密结果包含 IV + 密文 + HMAC，解密只需密钥
    """
    settings = get_settings()
    # 🛡️ 默认密钥仅限开发环境，生产环境不设置此变量应视为配置错误
    key = settings.api_key_encryption_key or "pJ4FjjK5LxJz7VwOqN_3kA6bT8xBv0bL1c2dF3eG4hI="
    return Fernet(key.encode())


def encrypt_api_key(plaintext: str) -> str:
    """
    加密 API 密钥明文，返回 Base64 编码的密文字符串。

    🎯 使用场景：
        - 用户创建/更新自有模型配置时加密其 API Key
        - 用户创建 HTTP 工具时加密其鉴权密钥

    ⚡ 性能：单次加密 < 0.1ms，AES 硬件加速下几乎无开销。
    """
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str:
    """
    解密 API 密钥密文，还原为明文。

    🛡️ 防御性设计：
        - Fernet 内部会验证 HMAC 签名，密文被篡改时抛出 InvalidToken 异常
        - 调用方应在安全上下文中使用解密结果，避免明文泄漏到日志或错误消息

    Raises:
        cryptography.fernet.InvalidToken: 密文损坏、密钥不匹配或密文被篡改时抛出
    """
    return _fernet().decrypt(ciphertext.encode()).decode()
