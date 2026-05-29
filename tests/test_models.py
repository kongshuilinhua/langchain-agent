from core.db.models import KnowledgeDocument
from core.db.session import SessionLocal, init_db

def test_knowledge_document_segment_config():
    init_db()
    db = SessionLocal()
    try:
        doc = KnowledgeDocument(
            knowledge_base_id=1,
            filename="test.md",
            title="Test Doc",
            content_type="text/markdown",
            source_type="text",
            text="# Title\nHello",
            segment_config={
                "parse_mode": "precise",
                "segment_mode": "hierarchy",
                "hierarchy_level": 3
            }
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        assert doc.segment_config["hierarchy_level"] == 3
        
        # 清理测试数据
        db.delete(doc)
        db.commit()
    finally:
        db.close()
