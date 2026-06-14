from core.integrations.llm import OpenAICompatibleProvider
from core.services.ingestion.context import IngestionContext
from core.services.ingestion.nodes import ChunkNode, EmbedNode
from core.services.ingestion.pipeline import IngestionNode, IngestionPipeline, IngestionPipelineError
from core.services.knowledge import chunk_csv, chunk_document
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


def _ctx():
    return IngestionContext(
        workspace_id=1, knowledge_base_id=1, document_id=1,
        filename="f.txt", content_type="text/plain", text="hello",
    )


def test_pipeline_runs_nodes_in_order_and_logs():
    order = []

    class A(IngestionNode):
        name = "a"
        def run(self, ctx):
            order.append("a")

    class B(IngestionNode):
        name = "b"
        def run(self, ctx):
            order.append("b")

    ctx = _ctx()
    IngestionPipeline([A(), B()]).run(ctx)
    assert order == ["a", "b"]
    assert [log["node"] for log in ctx.logs] == ["a", "b"]
    assert all(log["status"] == "succeeded" for log in ctx.logs)


def test_pipeline_records_failed_node_and_raises():
    class Boom(IngestionNode):
        name = "boom"
        def run(self, ctx):
            raise ValueError("kaboom")

    ctx = _ctx()
    try:
        IngestionPipeline([Boom()]).run(ctx)
        assert False, "should have raised"
    except IngestionPipelineError as exc:
        assert exc.node == "boom"
    assert ctx.logs[-1]["node"] == "boom"
    assert ctx.logs[-1]["status"] == "failed"


def test_chunk_document_csv_dispatch():
    children, parents = chunk_document(
        "name,price\n甲,10\n乙,20", content_type="text/csv", kb_id=1, document_id=2, segment_config=None
    )
    assert children and parents
    assert all("name" in c["text"] for c in children)


def test_chunk_document_text_returns_children_and_parents():
    text = "段落一。" * 400  # 足够长以产生多个父块
    children, parents = chunk_document(
        text, content_type="text/plain", kb_id=1, document_id=3, segment_config=None
    )
    assert children and parents
    parent_ids = {p["parent_id"] for p in parents}
    assert all(c["parent_id"] in parent_ids for c in children)


def test_chunk_document_hierarchy_has_no_separate_parents():
    md = "# H1\n正文一\n## H2\n正文二"
    children, parents = chunk_document(
        md, content_type="text/markdown", kb_id=1, document_id=4,
        segment_config={"segment_mode": "hierarchy"},
    )
    assert children
    assert parents == []


def test_parent_chunk_model_and_log_column_exist():
    from core.db.models import KnowledgeDocument, KnowledgeParentChunk

    cols = KnowledgeParentChunk.__table__.columns.keys()
    for name in ["workspace_id", "knowledge_base_id", "document_id", "parent_id", "text", "content_hash"]:
        assert name in cols
    assert "ingestion_log" in KnowledgeDocument.__table__.columns.keys()


def test_chunk_node_fills_children_and_parents():
    ctx = IngestionContext(
        workspace_id=1, knowledge_base_id=1, document_id=9,
        filename="d.txt", content_type="text/plain", text="内容。" * 400,
    )
    ChunkNode().run(ctx)
    assert ctx.children and ctx.parents


def test_embed_node_aligns_embeddings(monkeypatch):
    monkeypatch.setenv("LINGSHU_MOCK_LLM", "true")
    import core.config

    core.config.get_settings.cache_clear()
    ctx = IngestionContext(
        workspace_id=1, knowledge_base_id=1, document_id=9,
        filename="d.txt", content_type="text/plain", text="x",
    )
    ctx.children = [{"text": "a"}, {"text": "b"}]
    EmbedNode(OpenAICompatibleProvider()).run(ctx)
    assert len(ctx.embeddings) == 2
