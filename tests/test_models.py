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


import json

def test_calculator_ast_security():
    from core.services.tools import _exec_calculator
    
    # 安全的常规数学表达式
    res1 = _exec_calculator({"expression": "2 + 3 * 4"})
    assert "result" in json.loads(res1["content"])
    assert json.loads(res1["content"])["result"] == 14
    
    # 恶意的或不合法的 Python AST 语法节点（列表推导式、魔术方法等）
    res2 = _exec_calculator({"expression": "[x.__class__ for x in [1]]"})
    assert "error" in json.loads(res2["content"])
    
    # 恶意的代码注入（导入系统模块执行命令）
    res3 = _exec_calculator({"expression": "import os; os.system('echo 1')"})
    assert "error" in json.loads(res3["content"])
