"""对象存储后端（软依赖）。

🛡️ 与 vector_store / redis_store 同款「软依赖」：未配置（STORAGE_BACKEND=none，默认）或
   minio 未安装 / 连接失败时 available=False，上传服务自动回退到「base64 直存 DB」的现状，
   单机零配置照常可用，绝不因对象存储缺失而中断上传。

🎯 只把上传文件的「字节」搬出 DB（解决 base64 直存撑大 MySQL 行的问题）；
   多模态调用时由 core/services/uploads.resolve_image_data_url 按需取回转 base64
   （刻意不暴露对象库直链——外部 LLM 厂商够不到内网 MinIO）。
"""

from __future__ import annotations

import io
import logging

from core.config import get_settings

logger = logging.getLogger(__name__)


class ObjectStorage:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self._error = ""
        self.bucket = self.settings.storage_bucket
        if self.settings.storage_backend != "minio":
            return
        if not (self.settings.storage_endpoint and self.settings.storage_access_key and self.settings.storage_secret_key):
            self._error = "storage backend is 'minio' but endpoint/credentials are incomplete"
            return
        try:
            from minio import Minio

            self._client = Minio(
                self.settings.storage_endpoint,
                access_key=self.settings.storage_access_key,
                secret_key=self.settings.storage_secret_key,
                secure=self.settings.storage_secure,
            )
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket)
        except Exception as exc:
            self._client = None
            self._error = str(exc)[:240]

    @property
    def available(self) -> bool:
        return self._client is not None

    def put(self, key: str, data: bytes, content_type: str) -> bool:
        """写入对象，成功返回 True；不可用或出错返回 False（调用方据此回退 DB 内联）。"""
        if not self._client:
            return False
        try:
            self._client.put_object(self.bucket, key, io.BytesIO(data), length=len(data), content_type=content_type)
            return True
        except Exception as exc:
            logger.warning("object storage put failed: %s", str(exc)[:200])
            return False

    def get(self, key: str) -> bytes | None:
        """读取对象字节；不可用或出错返回 None。"""
        if not self._client:
            return None
        response = None
        try:
            response = self._client.get_object(self.bucket, key)
            return response.read()
        except Exception as exc:
            logger.warning("object storage get failed: %s", str(exc)[:200])
            return None
        finally:
            if response is not None:
                try:
                    response.close()
                    response.release_conn()
                except Exception:
                    pass

    def status(self) -> dict:
        configured = self.settings.storage_backend == "minio"
        return {
            "configured": configured,
            "available": self.available,
            "backend": "minio" if self.available else "none",
            "bucket": self.bucket if configured else None,
            "error": self._error or None,
        }


# 全局单例
object_storage = ObjectStorage()
