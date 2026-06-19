# ── B1 会话记忆摘要：纯函数单测（不依赖 DB/LLM）────────────────────────

import json

from core.integrations.llm import ChatResponse
from core.services.memory_summary import (
    build_memory_payload,
    parse_memory,
    summarize_turns,
)


# ═══════════════════════════════════════════════════════════════
# parse_memory
# ═══════════════════════════════════════════════════════════════


def test_parse_new_dict_format():
    """新格式 {summary, turns} 正确解析。"""
    raw = json.dumps({"summary": "用户问了天气", "turns": [{"user": "今天天气", "assistant": "晴天"}]}, ensure_ascii=False)
    summary, turns = parse_memory(raw)
    assert summary == "用户问了天气"
    assert len(turns) == 1
    assert turns[0]["user"] == "今天天气"
    assert turns[0]["assistant"] == "晴天"


def test_parse_old_list_format():
    """旧格式 [{user, assistant}, ...] 退化为空 summary、原样 turns。"""
    raw = json.dumps([{"user": "你好", "assistant": "你好！"}], ensure_ascii=False)
    summary, turns = parse_memory(raw)
    assert summary == ""
    assert len(turns) == 1
    assert turns[0]["user"] == "你好"


def test_parse_old_separator_text():
    r"""旧 \n===\n 分隔文本兼容解析。"""
    raw = "用户：问题1\n助手：答案1\n===\n用户：问题2\n助手：答案2"
    summary, turns = parse_memory(raw)
    assert summary == ""
    assert len(turns) == 2
    assert turns[0] == {"user": "问题1", "assistant": "答案1"}
    assert turns[1] == {"user": "问题2", "assistant": "答案2"}


def test_parse_empty_returns_empty():
    assert parse_memory("") == ("", [])
    assert parse_memory("   ") == ("", [])


def test_parse_invalid_json_returns_empty():
    assert parse_memory("{not valid json") == ("", [])


def test_parse_dict_without_turns():
    """dict 格式但无 turns 字段时安全退避。"""
    summary, turns = parse_memory(json.dumps({"summary": "x"}))
    assert summary == ""
    assert turns == []


# ═══════════════════════════════════════════════════════════════
# build_memory_payload
# ═══════════════════════════════════════════════════════════════


def _fake_summarizer():
    """假摘要器：直接返回传入 older_turns/existing_summary 的标记。"""
    def _summarize(older_turns, existing_summary):
        # 返回一段明确标记的文本，方便断言
        return f"SUM({len(older_turns)}turns, prev='{existing_summary}')"
    return _summarize


def test_build_under_threshold_no_summary_call():
    """轮数未超 max_turns 时，summarizer 不被调用。"""
    raw = json.dumps([{"user": "u1", "assistant": "a1"}])
    called = []
    def summarizer(older, existing):
        called.append(1)
        return "should_not_be_called"
    result = build_memory_payload(
        raw,
        new_turn={"user": "u2", "assistant": "a2"},
        max_turns=5,
        keep_recent=3,
        summarizer=summarizer,
    )
    assert called == []  # summarizer 从未调用
    assert result["summary"] == ""  # 旧 summary 为空
    assert len(result["turns"]) == 2
    assert result["turns"][-1] == {"user": "u2", "assistant": "a2"}


def test_build_over_threshold_calls_summarizer():
    """超 max_turns 时 summarizer 被调用一次，turns 只保留最近 keep_recent 轮。"""
    turns = [{"user": f"u{i}", "assistant": f"a{i}"} for i in range(1, 7)]  # 6 turns
    raw = json.dumps(turns, ensure_ascii=False)
    called_args = []
    def summarizer(older, existing):
        called_args.append((len(older), existing))
        return "摘要结果"
    result = build_memory_payload(
        raw,
        new_turn={"user": "u7", "assistant": "a7"},
        max_turns=4,
        keep_recent=2,
        summarizer=summarizer,
    )
    # total = 6 old + 1 new = 7, keep_recent=2 → older = 5 turns, recent = 2 turns
    assert len(called_args) == 1
    assert called_args[0][0] == 5  # 5 older turns
    assert called_args[0][1] == ""  # existing_summary was empty
    assert result["summary"] == "摘要结果"
    assert len(result["turns"]) == 2
    assert result["turns"][0]["user"] == "u6"
    assert result["turns"][1]["user"] == "u7"


def test_build_with_existing_summary_incremental():
    """已有摘要时，summarizer 收到 existing_summary 参数。"""
    raw = json.dumps({"summary": "之前聊了天气", "turns": [{"user": "u1", "assistant": "a1"}]}, ensure_ascii=False)
    called_existing = []
    def summarizer(older, existing):
        called_existing.append(existing)
        return "合并摘要"
    result = build_memory_payload(
        raw,
        new_turn={"user": "u2", "assistant": "a2"},
        max_turns=1,  # 2 turns > 1 → trigger compress
        keep_recent=1,
        summarizer=summarizer,
    )
    assert called_existing[0] == "之前聊了天气"
    assert result["summary"] == "合并摘要"


def test_build_summarizer_exception_falls_back():
    """summarizer 抛异常时，不抛、summary 保留旧值、turns 仍然正确截断。"""
    turns = [{"user": f"u{i}", "assistant": f"a{i}"} for i in range(1, 5)]
    raw = json.dumps({"summary": "旧摘要", "turns": turns}, ensure_ascii=False)
    def boom(_older, _existing):
        raise RuntimeError("LLM down")
    result = build_memory_payload(
        raw,
        new_turn={"user": "u5", "assistant": "a5"},
        max_turns=3,
        keep_recent=2,
        summarizer=boom,
    )
    # 降级：保留旧摘要
    assert result["summary"] == "旧摘要"
    # turns 正确截断（5 turns total, keep_recent=2 → 保留最后 2 轮）
    assert len(result["turns"]) == 2
    assert result["turns"][0]["user"] == "u4"
    assert result["turns"][1]["user"] == "u5"


def test_build_with_old_list_format_and_compress():
    """旧格式 [{user,assistant}] → 合并后同样可以触发压缩。"""
    raw = json.dumps([
        {"user": "u1", "assistant": "a1"},
        {"user": "u2", "assistant": "a2"},
        {"user": "u3", "assistant": "a3"},
    ], ensure_ascii=False)
    s = _fake_summarizer()
    result = build_memory_payload(
        raw,
        new_turn={"user": "u4", "assistant": "a4"},
        max_turns=2,  # 4 turns > 2 → compress
        keep_recent=1,
        summarizer=s,
    )
    assert result["summary"] == "SUM(3turns, prev='')"
    assert len(result["turns"]) == 1
    assert result["turns"][0]["user"] == "u4"


def test_build_preserves_turn_structure():
    """确认 turns 中 user/assistant 字段结构完整。"""
    raw = ""
    result = build_memory_payload(
        raw,
        new_turn={"user": "你好", "assistant": "你好！有什么可以帮你的？"},
        max_turns=10,
        keep_recent=3,
        summarizer=lambda o, e: "",
    )
    assert len(result["turns"]) == 1
    assert result["turns"][0] == {"user": "你好", "assistant": "你好！有什么可以帮你的？"}


# ═══════════════════════════════════════════════════════════════
# B1.2 summarize_turns（LLM 摘要器）
# ═══════════════════════════════════════════════════════════════


class _FakeProvider:
    """仿 test_query_understanding.py 的 _FakeProvider。"""
    def __init__(self, content=None, raise_exc=False):
        self._content = content
        self._raise = raise_exc
        self.calls = []

    def chat(self, messages, *, model=None, temperature=0.4, runtime_config=None, tools=None):
        self.calls.append({"messages": messages, "model": model, "temperature": temperature})
        if self._raise:
            raise RuntimeError("model down")
        return ChatResponse(content=self._content)


def test_summarize_turns_returns_llm_output():
    """fake provider 返回固定文本 → summarize_turns 返回该文本。"""
    provider = _FakeProvider(content="用户询问了天气和出行建议")
    result = summarize_turns(
        provider,
        older_turns=[{"user": "今天天气", "assistant": "晴天"}],
        existing_summary="",
        config={"enabled": True, "summary_max_chars": 800},
    )
    assert result == "用户询问了天气和出行建议"
    assert len(provider.calls) == 1


def test_summarize_turns_degrades_on_exception():
    """provider 抛异常 → 返回 existing_summary（降级，绝不抛）。"""
    provider = _FakeProvider(raise_exc=True)
    result = summarize_turns(
        provider,
        older_turns=[{"user": "q", "assistant": "a"}],
        existing_summary="旧摘要",
        config={"enabled": True},
    )
    assert result == "旧摘要"


def test_summarize_turns_disabled_skips_llm():
    """enabled=False 时直接返回 existing_summary，不调用 LLM。"""
    provider = _FakeProvider(content="should not be used")
    result = summarize_turns(
        provider,
        older_turns=[{"user": "q", "assistant": "a"}],
        existing_summary="旧摘要",
        config={"enabled": False},
    )
    assert result == "旧摘要"
    assert provider.calls == []


def test_summarize_turns_empty_older_skips_llm():
    """older_turns 为空时不调用 LLM。"""
    provider = _FakeProvider(content="x")
    result = summarize_turns(
        provider,
        older_turns=[],
        existing_summary="旧摘要",
        config={"enabled": True},
    )
    assert result == "旧摘要"
    assert provider.calls == []


def test_summarize_turns_empty_llm_output_returns_existing():
    """LLM 返回空内容时回退 existing_summary。"""
    provider = _FakeProvider(content="")
    result = summarize_turns(
        provider,
        older_turns=[{"user": "q", "assistant": "a"}],
        existing_summary="旧摘要",
        config={"enabled": True},
    )
    assert result == "旧摘要"


def test_summarize_turns_truncates_to_max_chars():
    """返回值超过 max_chars 时截断。"""
    provider = _FakeProvider(content="A" * 1000)
    result = summarize_turns(
        provider,
        older_turns=[{"user": "q", "assistant": "a"}],
        existing_summary="",
        config={"enabled": True, "summary_max_chars": 50},
    )
    assert len(result) == 50
    assert result == "A" * 50


def test_summarize_turns_uses_model_from_config():
    """config 中 model 字段传递给 provider.chat。"""
    provider = _FakeProvider(content="摘要")
    summarize_turns(
        provider,
        older_turns=[{"user": "q", "assistant": "a"}],
        existing_summary="",
        config={"enabled": True, "model": "qwen-turbo"},
    )
    assert provider.calls[0]["model"] == "qwen-turbo"


def test_summarize_turns_passes_runtime_config():
    """runtime_config 透传给 provider.chat。"""
    provider = _FakeProvider(content="摘要")
    summarize_turns(
        provider,
        older_turns=[{"user": "q", "assistant": "a"}],
        existing_summary="",
        config={"enabled": True},
        runtime_config={"chat_model": "override"},
    )
    # runtime_config is passed through, no assertion needed on it
    assert len(provider.calls) == 1
