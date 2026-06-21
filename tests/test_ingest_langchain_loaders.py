from pathlib import Path
from types import SimpleNamespace

import pytest

from core.services import knowledge, uploads


HTML = """<!doctype html><html><head><title>示例</title></head><body><p>正文内容</p></body></html>""".encode()


def _settings(enabled: bool):
    return SimpleNamespace(ingest_langchain_loaders=enabled)


def test_ingest_langchain_loader_setting_defaults_off(monkeypatch):
    from core.config import Settings

    monkeypatch.delenv("INGEST_LANGCHAIN_LOADERS", raising=False)
    assert Settings(_env_file=None).ingest_langchain_loaders is False


def test_extract_via_langchain_reads_local_html_and_removes_temp_file(monkeypatch):
    removed = []
    original_unlink = uploads.os.unlink

    def unlink(path):
        removed.append(path)
        original_unlink(path)

    monkeypatch.setattr(uploads.os, "unlink", unlink)
    text = uploads._extract_via_langchain("sample.html", HTML)

    assert "正文内容" in text
    assert len(removed) == 1
    assert not Path(removed[0]).exists()


def test_extract_document_text_uses_html_loader_when_enabled(monkeypatch):
    monkeypatch.setattr(uploads, "get_settings", lambda: _settings(True))

    text = uploads.extract_document_text("sample.html", "text/html", HTML)

    assert "正文内容" in text


def test_extract_document_text_rejects_html_when_disabled(monkeypatch):
    monkeypatch.setattr(uploads, "get_settings", lambda: _settings(False))

    with pytest.raises(ValueError, match="^Unsupported document type$"):
        uploads.extract_document_text("sample.html", "text/html", HTML)


def test_native_text_path_never_enters_langchain_loader(monkeypatch):
    monkeypatch.setattr(uploads, "get_settings", lambda: _settings(True))
    monkeypatch.setattr(
        uploads,
        "_extract_via_langchain",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("native path must not use LangChain")),
    )

    assert uploads.extract_document_text("note.txt", "text/plain", "原生正文".encode()) == "原生正文"


@pytest.mark.parametrize("enabled, expected", [(True, True), (False, False)])
def test_knowledge_admission_respects_loader_flag(monkeypatch, enabled, expected):
    monkeypatch.setattr(knowledge, "get_settings", lambda: _settings(enabled))

    assert knowledge._is_supported_file("sample.html", "text/html") is expected


@pytest.mark.parametrize("enabled, expected", [(True, "document"), (False, "unknown")])
def test_upload_kind_respects_loader_flag(monkeypatch, enabled, expected):
    monkeypatch.setattr(uploads, "get_settings", lambda: _settings(enabled))

    assert uploads._kind("text/html", "sample.html") == expected
