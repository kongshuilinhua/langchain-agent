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

import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken

from core.config import get_settings
from core.exceptions import AppException, ErrorCode

PREFIX = "fernet:"


def _fernet() -> Fernet:
    """
    获取 Fernet 加密器实例。

    🎯 密钥来源：
        从 API_KEY_ENCRYPTION_KEY 环境变量获取。为了能使用任意长度的字符串（如 64 字节密钥），
        我们使用 SHA256 进行哈希处理，并将其 Base64 编码为 32 字节的 URL-safe 密钥。

    🛡️ 安全设计（Fail-Fast）：
        如果生产环境未配置 API_KEY_ENCRYPTION_KEY，直接抛出 AppException 阻断服务。
        不再允许硬编码默认密钥兜底。
    """
    settings = get_settings()
    if not settings.api_key_encryption_key:
        raise AppException(
            ErrorCode.ENCRYPTION_NOT_CONFIGURED,
            message="API_KEY_ENCRYPTION_KEY 未配置，无法安全存储用户的第三方 API 密钥。"
                    "请运行: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
                    "生成密钥并设置到环境变量中。",
            status_code=503,
        )
    
    digest = hashlib.sha256(settings.api_key_encryption_key.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_api_key(plaintext: str) -> str:
    """
    加密 API 密钥明文，返回带有 'fernet:' 前缀的 Base64 编码密文字符串。
    """
    value = plaintext.strip()
    if not value:
        raise ValueError("API key cannot be empty")
    return PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(ciphertext: str) -> str:
    """
    解密 API 密钥密文，还原为明文。支持带 'fernet:' 前缀与不带前缀的格式。
    """
    value = ciphertext or ""
    if value.startswith(PREFIX):
        token = value.removeprefix(PREFIX).encode("ascii")
    else:
        token = value.encode("ascii")
        
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise ValueError("Stored API key is invalid") from exc


def secret_storage_ready() -> bool:
    """
    检查安全密钥存储是否已准备就绪。
    如果配置了 API_KEY_ENCRYPTION_KEY，则返回 True。
    """
    settings = get_settings()
    return bool(settings.api_key_encryption_key)
