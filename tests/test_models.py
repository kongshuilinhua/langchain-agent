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


def test_builtin_tools_implementation():
    from core.services.tools import (
        _exec_password_generator,
        _exec_uuid_generator,
        _exec_character_counter,
        _exec_diff_checker,
        _exec_currency_converter,
        _exec_qr_generator,
        _exec_joke_generator,
        _exec_advice_slip,
        _exec_bored_activity,
        _exec_horoscope,
        _exec_image_search,
        _exec_news_search,
    )
    
    # Test password generator
    pw_res = _exec_password_generator({"length": 16})
    pw_data = json.loads(pw_res["content"])
    assert len(pw_data["password"]) == 16
    
    # Test UUID generator
    uuid_res = _exec_uuid_generator({"count": 5})
    uuid_data = json.loads(uuid_res["content"])
    assert len(uuid_data["uuids"]) == 5
    
    # Test character counter
    char_res = _exec_character_counter({"text": "Hello World"})
    char_data = json.loads(char_res["content"])
    assert char_data["characters"] == 11
    assert char_data["words"] == 2
    
    # Test diff checker
    diff_res = _exec_diff_checker({"text1": "Line 1\nLine 2", "text2": "Line 1\nLine 3"})
    diff_data = json.loads(diff_res["content"])
    assert "diff" in diff_data
    
    # Test currency converter
    curr_res = _exec_currency_converter({"from_currency": "USD", "to_currency": "CNY", "amount": 100})
    curr_data = json.loads(curr_res["content"])
    assert curr_data["from"] == "USD"
    assert curr_data["to"] == "CNY"
    assert curr_data["amount"] == 100
    assert "result" in curr_data
    
    # Test QR generator
    qr_res = _exec_qr_generator({"text": "https://example.com"})
    qr_data = json.loads(qr_res["content"])
    assert "qr_code_url" in qr_data
    
    # Test joke generator
    joke_res = _exec_joke_generator({})
    joke_data = json.loads(joke_res["content"])
    assert "setup" in joke_data
    assert "punchline" in joke_data
    
    # Test advice slip
    adv_res = _exec_advice_slip({})
    adv_data = json.loads(adv_res["content"])
    assert "advice" in adv_data
    
    # Test bored activity
    bored_res = _exec_bored_activity({})
    bored_data = json.loads(bored_res["content"])
    assert "activity" in bored_data
    
    # Test horoscope
    horo_res = _exec_horoscope({"sign": "白羊座"})
    horo_data = json.loads(horo_res["content"])
    assert horo_data["sign"] == "白羊座"
    assert "summary" in horo_data
    
    # Test image search
    img_res = _exec_image_search({"query": "nature"})
    img_data = json.loads(img_res["content"])
    assert len(img_data["images"]) > 0
    
    # Test news search
    news_res = _exec_news_search({"category": "tech"})
    news_data = json.loads(news_res["content"])
    assert len(news_data["news"]) > 0

