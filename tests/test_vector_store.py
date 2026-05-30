from core.integrations.vector_store import build_milvus_filter


def test_build_milvus_filter():
    expr = build_milvus_filter({"workspace_id": 1, "knowledge_base_id": 2, "document_id": "doc-1"})

    assert "workspace_id == 1" in expr
    assert "knowledge_base_id == 2" in expr
    assert 'document_id == "doc-1"' in expr

