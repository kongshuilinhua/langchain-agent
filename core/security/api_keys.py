from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from core.config import get_settings


PREFIX = "fernet:"
DEFAULT_SECRET = "change-me-in-production"


def secret_storage_ready() -> bool:
    settings = get_settings()
    return bool(settings.api_key_encryption_key) or bool(settings.jwt_secret and settings.jwt_secret != DEFAULT_SECRET)


def require_secret_storage_ready() -> None:
    settings = get_settings()
    if settings.mock_llm:
        return
    if not secret_storage_ready():
        raise ValueError("Secure API key encryption is not configured")


def encrypt_api_key(api_key: str) -> str:
    require_secret_storage_ready()
    value = api_key.strip()
    if not value:
        raise ValueError("API key cannot be empty")
    return PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(encrypted_api_key: str) -> str:
    require_secret_storage_ready()
    value = encrypted_api_key or ""
    if not value.startswith(PREFIX):
        raise ValueError("Stored API key is invalid")
    token = value.removeprefix(PREFIX).encode("ascii")
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise ValueError("Stored API key is invalid") from exc


def _fernet() -> Fernet:
    settings = get_settings()
    encryption_key = settings.api_key_encryption_key
    
    if not encryption_key:
        # Allow insecure dev fallback only when running mock LLM tests
        if settings.mock_llm:
            fallback_secret = b"dev-mode-insecure-transient-secret-key"
        else:
            raise ValueError(
                "CRITICAL SECURITY ERROR: 'API_KEY_ENCRYPTION_KEY' environment variable "
                "is not configured. Reusing JWT_SECRET for db encryption is blocked "
                "to prevent credentials compromise."
            )
    else:
        fallback_secret = encryption_key.encode("utf-8")
        
    digest = hashlib.sha256(fallback_secret).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
