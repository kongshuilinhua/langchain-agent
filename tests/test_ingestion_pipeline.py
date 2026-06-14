from core.integrations.llm import OpenAICompatibleProvider
from core.services.knowledge import chunk_csv
from core.services.uploads import decode_bytes


def test_decode_bytes_utf8():
    assert decode_bytes("知识库内容".encode("utf-8")) == "知识库内容"


def test_decode_bytes_gbk():
    # 中文 Windows 常见的 GBK 文本，不应解码成乱码
    assert decode_bytes("产品保修期".encode("gbk")) == "产品保修期"


def test_decode_bytes_garbage_does_not_raise():
    result = decode_bytes(b"\xff\xfe\x00bad")
    assert isinstance(result, str)


def test_embed_batch_mock_counts_and_matches(monkeypatch):
    monkeypatch.setenv("LINGSHU_MOCK_LLM", "true")
    import core.config

    core.config.get_settings.cache_clear()
    provider = OpenAICompatibleProvider()
    vectors = provider.embed_batch(["甲", "乙", "丙"])
    assert len(vectors) == 3
    assert all(len(v) == 32 for v in vectors)
    assert provider.embed_batch(["甲"])[0] == provider.embed("甲")


def test_embed_batch_empty():
    provider = OpenAICompatibleProvider()
    assert provider.embed_batch([]) == []


def test_chunk_csv_header_in_every_child():
    text = "name,price\n甲,10\n乙,20\n丙,30"
    children, parents = chunk_csv(text, kb_id=1, document_id=1, rows_per_child=2, rows_per_parent=4)
    assert children
    assert parents
    for child in children:
        assert "name" in child["text"] and "price" in child["text"]
    joined = " ".join(c["text"] for c in children)
    assert "甲" in joined and "丙" in joined


def test_chunk_csv_empty():
    assert chunk_csv("", kb_id=1, document_id=1) == ([], [])
