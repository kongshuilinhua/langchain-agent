"""对象存储后端 + resolve_image_data_url 单元测试（不依赖真实 MinIO / DB）。"""

import base64
from types import SimpleNamespace

from core.config import get_settings
from core.integrations import storage as storage_module
from core.services import uploads as uploads_module


class _FakeObj:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self):
        return self._data

    def close(self):
        pass

    def release_conn(self):
        pass


class FakeMinioClient:
    def __init__(self) -> None:
        self.store: dict[tuple, bytes] = {}

    def put_object(self, bucket, key, stream, length, content_type):
        self.store[(bucket, key)] = stream.read()

    def get_object(self, bucket, key):
        if (bucket, key) not in self.store:
            raise KeyError("not found")
        return _FakeObj(self.store[(bucket, key)])


def _storage(client) -> storage_module.ObjectStorage:
    store = storage_module.ObjectStorage.__new__(storage_module.ObjectStorage)
    store.settings = get_settings()
    store._client = client
    store._error = ""
    store.bucket = "b"
    return store


def test_storage_unavailable_by_default():
    store = _storage(None)
    assert store.available is False
    assert store.put("k", b"x", "image/png") is False
    assert store.get("k") is None


def test_storage_put_get_roundtrip():
    store = _storage(FakeMinioClient())
    assert store.available is True
    assert store.put("k", b"hello", "image/png") is True
    assert store.get("k") == b"hello"
    assert store.get("missing") is None  # get_object 抛错 → 降级 None


def test_resolve_prefers_inline_data_url():
    upload = SimpleNamespace(data_url="data:image/png;base64,AAAA", storage_key="", content_type="image/png", kind="image")
    assert uploads_module.resolve_image_data_url(upload) == "data:image/png;base64,AAAA"


def test_resolve_from_object_storage(monkeypatch):
    store = _storage(FakeMinioClient())
    store.put("images/1/u", b"PNGBYTES", "image/png")
    monkeypatch.setattr(uploads_module, "object_storage", store)
    upload = SimpleNamespace(data_url="", storage_key="images/1/u", content_type="image/png", kind="image")
    expected = "data:image/png;base64," + base64.b64encode(b"PNGBYTES").decode("ascii")
    assert uploads_module.resolve_image_data_url(upload) == expected


def test_resolve_empty_when_no_source(monkeypatch):
    monkeypatch.setattr(uploads_module, "object_storage", _storage(FakeMinioClient()))
    upload = SimpleNamespace(data_url="", storage_key="", content_type="image/png", kind="image")
    assert uploads_module.resolve_image_data_url(upload) == ""
