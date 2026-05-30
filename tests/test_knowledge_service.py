# filepath: d:/pycharmprojects/langchain/tests/test_knowledge_service.py
from core.services.knowledge import split_by_hierarchy

def test_split_by_hierarchy():
    markdown_text = "# H1\nText under H1\n## H2\nText under H2\n### H3\nText under H3"
    # 测试三级层级切分
    chunks = split_by_hierarchy(markdown_text, kb_id=1, document_id=1, max_level=3)
    
    assert len(chunks) == 3
    assert chunks[0]["section"] == "H1: H1"
    assert chunks[1]["section"] == "H1: H1 > H2: H2"
    assert chunks[2]["section"] == "H1: H1 > H2: H2 > H3: H3"

def test_split_by_hierarchy_fallback():
    # If no headers match, it should fall back to split_parent_child
    text = "Just some text without any headings here. It should be split using parent-child logic."
    chunks = split_by_hierarchy(text, kb_id=1, document_id=1)
    assert len(chunks) > 0
    assert chunks[0]["parent_id"].startswith("kb1-doc1-parent0")

def test_split_by_hierarchy_max_level():
    # If max_level is 2, H3 heading should not be treated as a split point,
    # but its content should be preserved as part of the parent H2 section.
    markdown_text = "# H1\nText 1\n## H2\nText 2\n### H3\nText 3"
    chunks = split_by_hierarchy(markdown_text, kb_id=1, document_id=1, max_level=2)
    assert len(chunks) == 2
    assert chunks[0]["section"] == "H1: H1"
    assert chunks[1]["section"] == "H1: H1 > H2: H2"
    assert "Text 2" in chunks[1]["text"]
    assert "Text 3" in chunks[1]["text"]

def test_split_by_hierarchy_intro():
    # Verify that introductory text before the first heading is successfully captured
    markdown_text = "This is introductory text.\n# H1\nText 1"
    chunks = split_by_hierarchy(markdown_text, kb_id=1, document_id=1, max_level=3)
    assert len(chunks) == 2
    assert chunks[0]["section"] == "前言"
    assert chunks[0]["text"] == "This is introductory text."
    assert chunks[1]["section"] == "H1: H1"
    assert chunks[1]["text"] == "H1\nText 1"

def test_split_by_hierarchy_no_keep_hierarchy():
    markdown_text = "# H1\nText 1"
    chunks = split_by_hierarchy(markdown_text, kb_id=1, document_id=1, keep_hierarchy_info=False)
    assert len(chunks) == 1
    assert chunks[0]["section"] == ""
