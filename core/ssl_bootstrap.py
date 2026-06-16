"""
🛡️ SSL 证书环境自愈模块。

🎯 架构角色与背景：
    conda 在激活环境时会注入 `SSL_CERT_FILE`/`SSL_CERT_DIR`，指向
    `$CONDA_PREFIX/ssl/cacert.pem`。但当 `ca-certificates` 包缺失或被裁剪时，
    该文件并不存在。

    httpx 在创建 Client 时（trust_env=True）会无条件读取 `os.environ["SSL_CERT_FILE"]`
    作为 CA 包——哪怕只是发一个纯 HTTP 请求，也会在 SSL context 初始化阶段因
    文件缺失抛出 `FileNotFoundError: [Errno 2] No such file or directory`，
    导致所有走 httpx 的工具（arxiv/wikipedia/weather/web_search…）整体瘫痪。

🛡️ 自愈策略（仅在损坏时介入，正常环境零副作用）：
    若 `SSL_CERT_FILE` 已设置但指向的文件不存在，则把它（以及同样失效的
    `SSL_CERT_DIR`）重定向到 certifi 自带的有效 CA 包。不修改用户的 conda 环境，
    进程级生效，一次修复 httpx / ssl / 其它读取该变量的库。
"""
from __future__ import annotations

import os


def ensure_valid_ssl_cert_file() -> str | None:
    """检测并修复失效的 SSL_CERT_FILE，返回最终生效的 CA 包路径（无需修复则返回原值）。"""
    cert_file = os.environ.get("SSL_CERT_FILE")
    cert_dir = os.environ.get("SSL_CERT_DIR")

    file_broken = bool(cert_file) and not os.path.isfile(cert_file)
    dir_broken = bool(cert_dir) and not os.path.isdir(cert_dir)
    if not file_broken and not dir_broken:
        return cert_file

    try:
        import certifi
        valid_bundle = certifi.where()
    except Exception:
        return cert_file
    if not os.path.isfile(valid_bundle):
        return cert_file

    if file_broken:
        os.environ["SSL_CERT_FILE"] = valid_bundle
    # SSL_CERT_DIR 失效时直接移除，交由证书文件兜底（错误的目录会让 OpenSSL 校验失败）
    if dir_broken:
        os.environ.pop("SSL_CERT_DIR", None)
    # requests / 部分库读取 REQUESTS_CA_BUNDLE，未设置时一并补上保持一致
    os.environ.setdefault("REQUESTS_CA_BUNDLE", valid_bundle)
    return os.environ.get("SSL_CERT_FILE")
