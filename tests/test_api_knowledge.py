# filepath: d:/pycharmprojects/langchain/tests/test_api_knowledge.py
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

def test_preview_chunks_api():
    # 测试路由绑定
    payload = {
        "parse_mode": "precise",
        "segment_mode": "hierarchy",
        "hierarchy_level": 2,
        "keep_hierarchy_info": True
    }
    # 假定 document_id = 1, kb_id = 1
    response = client.post("/api/knowledge-bases/1/documents/1/preview", json=payload, headers={"Authorization": "Bearer test-token"})
    assert response.status_code in [200, 401] # 401 正常(无 auth token 下)，我们只测试路由绑定


def test_preview_and_resegment_integration(client, auth_headers):
    # 1. 创建知识库
    kb = client.post("/api/knowledge-bases", headers=auth_headers, json={"name": "Custom Segmentation KB"})
    assert kb.status_code == 200
    kb_id = kb.json()["knowledge_base"]["id"]

    # 2. 上传文档
    document = client.post(
        f"/api/knowledge-bases/{kb_id}/documents",
        headers=auth_headers,
        json={
            "title": "Hierarchical Doc",
            "content": "# Main Title\nThis is main intro text.\n## Section 1\nDetailed content 1.\n## Section 2\nDetailed content 2.",
            "source_type": "text",
        },
    )
    assert document.status_code == 200
    doc_id = document.json()["document"]["id"]

    # 3. 预览分段 API 测试 - hierarchy mode
    payload = {
        "parse_mode": "precise",
        "segment_mode": "hierarchy",
        "hierarchy_level": 2,
        "keep_hierarchy_info": True
    }
    response = client.post(f"/api/knowledge-bases/{kb_id}/documents/{doc_id}/preview", json=payload, headers=auth_headers)
    assert response.status_code == 200
    res = response.json()
    assert res["chunks_count"] == 3
    assert res["preview_items"][0]["hierarchy_path"] == "H1: Main Title"
    assert "Main Title" in res["preview_items"][0]["text"]
    assert res["preview_items"][1]["hierarchy_path"] == "H1: Main Title > H2: Section 1"
    assert "Section 1" in res["preview_items"][1]["text"]

    # 4. 预览分段 API 测试 - custom mode (parent-child with custom sizes)
    payload_custom = {
        "parse_mode": "precise",
        "segment_mode": "custom",
        "max_chunk_len": 500,
        "overlap_pct": 10
    }
    response_custom = client.post(f"/api/knowledge-bases/{kb_id}/documents/{doc_id}/preview", json=payload_custom, headers=auth_headers)
    assert response_custom.status_code == 200
    res_custom = response_custom.json()
    assert res_custom["chunks_count"] > 0

    # 5. 重新分段 API 测试
    resegment_payload = {
        "parse_mode": "precise",
        "segment_mode": "hierarchy",
        "hierarchy_level": 2,
        "keep_hierarchy_info": True
    }
    response_resegment = client.post(
        f"/api/knowledge-bases/{kb_id}/documents/{doc_id}/resegment",
        json=resegment_payload,
        headers=auth_headers
    )
    assert response_resegment.status_code == 200
    res_resegment = response_resegment.json()
    assert res_resegment["document"]["segment_config"]["segment_mode"] == "hierarchy"
    assert res_resegment["document"]["segment_config"]["hierarchy_level"] == 2

    # 6. 验证数据库中分段已更新
    chunks_response = client.get(f"/api/knowledge-bases/{kb_id}/documents/{doc_id}/chunks", headers=auth_headers)
    assert chunks_response.status_code == 200
    chunks_res = chunks_response.json()
    assert chunks_res["document"]["chunk_count"] == 3
    assert len(chunks_res["chunks"]) == 3
