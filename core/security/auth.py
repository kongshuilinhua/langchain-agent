"""
灵枢 Agent 平台 —— 安全认证模块。

🎯 架构角色：
    本模块是平台安全体系的基石，提供两大核心能力：
    1. 密码哈希：使用 PBKDF2-HMAC-SHA256 将明文密码转为不可逆摘要
    2. JWT 令牌：签发/验证无状态的访问令牌，驱动 API 层的身份识别

    在整个请求生命周期中，本模块处于最前端：
    HTTP 请求 → FastAPI deps.py(提取 Bearer Token) → auth.decode_access_token → 用户身份确认
"""

import hashlib
import hmac
import os
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from core.config import get_settings


# ═══════════════════════════════════════════════════════════════
# 密码哈希（Password Hashing）
# ═══════════════════════════════════════════════════════════════


def hash_password(password: str) -> str:
    """
    将明文密码转化为安全的不可逆哈希值。

    🎯 设计意图：
        使用 PBKDF2-HMAC-SHA256 慢哈希算法，通过大量迭代将计算成本提升到
        暴力破解不可行的程度。每次调用随机生成 16 字节盐值(salt)，确保相同
        密码产生不同摘要，抵御彩虹表攻击。

    🧠 参数解析：
        - iterations=210000: OWASP 2023 推荐的最低迭代次数。
          每次哈希需要约 100-200ms CPU 时间，攻击者暴力枚举 1 亿个密码
          需要约 231 天（单核），有效遏制离线破解。
          值过低(如 1000) → 毫秒级可破解；值过高(如 100万) → 登录延迟不可接受。
        - salt=16字节: 128 位随机盐，碰撞概率 < 2^-64，实践中视为不可能。

    返回格式: "pbkdf2:iterations:hex(salt):hex(hash)"
    """
    salt = os.urandom(16)
    iterations = 210_000
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2:{iterations}:{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """
    验证用户输入的明文密码是否与存储的哈希匹配。

    🛡️ 防御性设计：
        1. 使用 hmac.compare_digest 做恒定时间比较，防止计时侧信道攻击
           (timing attack)：攻击者无法通过响应时间差异推断哈希的前缀匹配程度
        2. 外层 try/except 兜底所有解析错误（格式损坏、字段缺失等），
           确保任何异常情况都返回 False 而非抛出异常泄漏内部信息
    """
    try:
        parts = stored.split(":")
        # 格式校验：必须为 "pbkdf2:iterations:salt:hash" 四段
        if len(parts) != 4 or parts[0] != "pbkdf2":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        stored_hash = bytes.fromhex(parts[3])
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        # 🛡️ 恒定时间比较：即使哈希不匹配，比较耗时也相同，防止计时攻击
        return hmac.compare_digest(dk, stored_hash)
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# JWT 令牌（JSON Web Token）
# ═══════════════════════════════════════════════════════════════

# 🎯 设计决策：手动实现 JWT 而非使用 PyJWT 库
# 原因：减少第三方依赖、完全掌控安全边界、代码量极小（<30行核心逻辑）
# 局限：仅支持 HS256，若需 RS256 非对称签名或 JWK 密钥轮转则应引入标准库

import json


def create_access_token(data: dict) -> str:
    """
    签发 JWT 访问令牌。

    🎯 工作原理：
        JWT 由三部分组成：Header.Payload.Signature
        - Header: 声明签名算法（HS256）
        - Payload: 携带用户 ID(sub)、过期时间(exp) 等声明
        - Signature: HMAC-SHA256(Header.Payload, secret)，保证完整性

    🧠 过期时间设计：
        默认 24 小时有效期，过期后前端需引导重新登录。
        未实现 Refresh Token 机制——对于内部工具平台，这种简化是合理的。
        若面向公网用户，应增加短期 Access Token + 长期 Refresh Token 双令牌方案。

    ⚡ 性能：纯 Python 计算，单次签发 < 0.1ms，无 I/O 开销。
    """
    settings = get_settings()
    payload = dict(data)
    # 过期时间戳：当前 UTC 秒数 + 配置的有效分钟数
    payload["exp"] = int(time.time()) + settings.access_token_minutes * 60
    # JWT Header：固定为 HS256 对称签名
    header = {"alg": settings.jwt_algorithm, "typ": "JWT"}
    # 构造 Header.Payload 的 Base64URL 编码
    h = _b64url_encode(json.dumps(header).encode())
    p = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{h}.{p}"
    # HMAC-SHA256 签名：使用 jwt_secret 作为密钥
    sig = hmac.new(settings.jwt_secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(sig)}"


def decode_access_token(token: str) -> dict:
    """
    验证并解码 JWT 访问令牌。

    🛡️ 安全校验链：
        1. 结构完整性：必须为三段式 Header.Payload.Signature 格式
        2. 签名验证：重新计算 HMAC 并恒定时间比较，防止篡改
        3. 过期检查：exp 必须大于当前时间戳
        4. 主体检查：sub 字段必须存在，代表用户 ID

    Raises:
        ValueError: 任何验证失败（格式错误、签名不匹配、过期、无效载荷）
    """
    settings = get_settings()
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")
    h, p, s = parts
    # 🛡️ 签名验证：恒定时间比较，防止计时攻击
    expected = hmac.new(settings.jwt_secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url_decode(s), expected):
        raise ValueError("Invalid signature")
    payload = json.loads(_b64url_decode(p))
    # 🛡️ 过期校验：防止被截获的过期令牌重放
    if payload.get("exp", 0) < time.time():
        raise ValueError("Token expired")
    if "sub" not in payload:
        raise ValueError("Missing subject")
    return payload


def _b64url_encode(data: bytes) -> str:
    """Base64URL 编码（无填充），符合 RFC 7515 JWS 规范。"""
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """
    Base64URL 解码（自动补填充）。

    🛡️ 补齐 '=' 填充字符：Base64 编码长度必须是 4 的倍数，
    JWT 规范中传输时会省略填充符，解码前需要还原。
    """
    s += "=" * (-len(s) % 4)
    return urlsafe_b64decode(s)
