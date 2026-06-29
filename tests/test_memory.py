# -*- coding: utf-8 -*-
from datetime import datetime, timezone, timedelta
from core.services.memory import normalize_facts

def test_normalize_facts_handles_strings():
    """测试将纯字符串输入转换为标准字典格式。"""
    input_facts = ["  First fact  ", "Second fact"]
    normalized = normalize_facts(input_facts)
    
    assert len(normalized) == 2
    for item in normalized:
        assert isinstance(item, dict)
        assert "id" in item
        assert len(item["id"]) == 8
        assert "text" in item
        assert "source" in item
        assert item["source"] == "user"
        assert "created_at" in item
        assert "score" in item
        assert item["score"] == 1.0
        
    assert normalized[0]["text"] == "First fact"
    assert normalized[1]["text"] == "Second fact"

def test_normalize_facts_handles_dicts_and_validation():
    """测试对字典输入字段的验证与补全。"""
    created_time = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    input_facts = [
        {
            "id": "12345678",
            "text": "Existing valid fact",
            "source": "assistant",
            "created_at": created_time,
            "score": 0.8
        },
        {
            "text": "   Fact with missing fields   "
        },
        {
            "id": 9999,  # invalid id type
            "text": "Fact with invalid ID",
            "score": "invalid_score"  # invalid score type
        }
    ]
    
    normalized = normalize_facts(input_facts)
    assert len(normalized) == 3
    
    # 用 text 查找对应项
    item0 = next(item for item in normalized if item["text"] == "Existing valid fact")
    assert item0["id"] == "12345678"
    assert item0["source"] == "assistant"
    assert item0["created_at"] == created_time
    assert item0["score"] == 0.8
    
    item1 = next(item for item in normalized if item["text"] == "Fact with missing fields")
    assert len(item1["id"]) == 8
    assert item1["source"] == "user"
    assert item1["score"] == 1.0
    assert "created_at" in item1
    
    item2 = next(item for item in normalized if item["text"] == "Fact with invalid ID")
    assert len(item2["id"]) == 8
    assert item2["source"] == "user"
    assert item2["score"] == 1.0  # fallback to default score

def test_normalize_facts_deduplication():
    """测试排重逻辑：统一转换为小写，去除非字母、数字和中文字符，更新 max score 和最新的 created_at。"""
    now = datetime.now(timezone.utc)
    time1 = (now - timedelta(hours=2)).isoformat()
    time2 = (now - timedelta(hours=1)).isoformat()
    time3 = now.isoformat()
    
    input_facts = [
        # 第一个事实
        {
            "id": "f1",
            "text": "Hello, World!!!",
            "source": "user",
            "created_at": time1,
            "score": 0.5
        },
        # 重复事实：标点不同，大小写不同，score 更高，created_at 更晚
        {
            "id": "f2",
            "text": "hello world?",
            "source": "user",
            "created_at": time2,
            "score": 0.9
        },
        # 重复事实：score 更低，created_at 更早
        {
            "id": "f3",
            "text": "HELLO   WORLD!!!",
            "source": "user",
            "created_at": time1,
            "score": 0.3
        },
        # 中文测试：标点符号过滤排重
        {
            "id": "f4",
            "text": "你好，世界！",
            "source": "user",
            "created_at": time2,
            "score": 0.6
        },
        # 重复中文事实，更新为更晚的 time3
        {
            "id": "f5",
            "text": "你好世界",
            "source": "user",
            "created_at": time3,
            "score": 0.8
        }
    ]
    
    normalized = normalize_facts(input_facts)
    assert len(normalized) == 2
    
    # 验证 "Hello, World!!!" 和 "hello world?" / "HELLO   WORLD!!!" 合并
    hello_world_fact = next(f for f in normalized if f["id"] == "f1")
    assert hello_world_fact["text"] == "Hello, World!!!"  # 应保留第一次出现的 text 格式（或者 normalized，但原样 text 保留更合理）
    assert hello_world_fact["score"] == 0.9  # max of 0.5, 0.9, 0.3
    assert hello_world_fact["created_at"] == time2  # newer of time1, time2, time1
    
    # 验证中文合并
    chinese_fact = next(f for f in normalized if f["id"] == "f4")
    assert chinese_fact["text"] == "你好，世界！"
    assert chinese_fact["score"] == 0.8  # max of 0.6, 0.8
    assert chinese_fact["created_at"] == time3  # newer of time2, time3

def test_normalize_facts_decay_and_eviction():
    """测试衰减排序和前50条截断。"""
    now = datetime.now(timezone.utc)
    
    # 构建 60 个不同事实，不同时间以测试衰减排序
    # 衰减公式: score * (0.95 ** days_old)
    input_facts = []
    # 第 1 组：今天创建，score=0.8，衰减后 score=0.8
    for i in range(25):
        input_facts.append({
            "text": f"Today Fact {i}",
            "score": 0.8,
            "created_at": now.isoformat()
        })
    # 第 2 组：10 天前创建，score=1.0，衰减后 score = 1.0 * (0.95 ** 10) = 0.598
    for i in range(25):
        input_facts.append({
            "text": f"Old Fact {i}",
            "score": 1.0,
            "created_at": (now - timedelta(days=10)).isoformat()
        })
    # 第 3 组：100 天前创建，score=1.0，衰减后接近 0，必被淘汰
    for i in range(15):
        input_facts.append({
            "text": f"Ancient Fact {i}",
            "score": 1.0,
            "created_at": (now - timedelta(days=100)).isoformat()
        })
        
    normalized = normalize_facts(input_facts)
    # 应只保留 50 个
    assert len(normalized) == 50
    
    # 前 25 个应该是 Today Fact，因为衰减后分数更高 (0.8 > 0.598)
    today_facts_count = sum(1 for f in normalized[:25] if "Today" in f["text"])
    assert today_facts_count == 25
    
    # 后 25 个应该是 Old Fact，而 Ancient Fact 全部被淘汰
    old_facts_count = sum(1 for f in normalized[25:] if "Old" in f["text"])
    assert old_facts_count == 25
    
    # 验证排序是按衰减分从大到小
    # 计算衰减分并检查是否单调递减
    decayed_scores = []
    for f in normalized:
        dt = datetime.fromisoformat(f["created_at"])
        days_old = (now - dt).total_seconds() / 86400.0
        decayed = f["score"] * (0.95 ** days_old)
        decayed_scores.append(decayed)
        
    for i in range(len(decayed_scores) - 1):
        assert decayed_scores[i] >= decayed_scores[i+1]
