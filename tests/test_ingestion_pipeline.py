from core.services.uploads import decode_bytes


def test_decode_bytes_utf8():
    assert decode_bytes("知识库内容".encode("utf-8")) == "知识库内容"


def test_decode_bytes_gbk():
    # 中文 Windows 常见的 GBK 文本，不应解码成乱码
    assert decode_bytes("产品保修期".encode("gbk")) == "产品保修期"


def test_decode_bytes_garbage_does_not_raise():
    result = decode_bytes(b"\xff\xfe\x00bad")
    assert isinstance(result, str)
