"""
会话记忆摘要服务。

🎯 照搬 ragent JdbcConversationMemorySummaryService / DefaultConversationMemoryService 的
   摘要压缩 + 加载装配逻辑，翻译成 Python 纯函数。

模式：
  - parse_memory → 兼容解析三种历史格式，纯函数
  - build_memory_payload → 合并当前轮、超阈值压缩、降级保旧，纯函数（summarizer 注入）
  - summarize_turns → LLM 调用 + 异常降级，仿 query_understanding.analyze 模式
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# ── 解析 ─────────────────────────────────────────────────────────────


def parse_memory(raw: str) -> tuple[str, list[dict]]:
    """
    兼容解析旧 summary：新 dict{summary,turns} / 旧 list[turn] / 旧 \\n===\\n 文本。
    返回 (summary, turns)。失败返回 ('', [])。

    🎯 对照 ragent JdbcConversationMemoryStore.loadHistory：
       解析 DB 中的消息列表 + summary 记录，装配为 ChatMessage 列表。
    """
    if not raw or not raw.strip():
        return "", []

    trimmed = raw.strip()

    # 1) 尝试 JSON 解析
    try:
        data = json.loads(trimmed)
    except (json.JSONDecodeError, ValueError):
        data = None

    if isinstance(data, dict):
        # 新格式: {"summary": "...", "turns": [...]}
        summary = str(data.get("summary") or "")
        turns = data.get("turns")
        if isinstance(turns, list):
            return summary, [t for t in turns if isinstance(t, dict) and "user" in t and "assistant" in t]
        return "", []

    if isinstance(data, list):
        # 旧格式: [{"user": ..., "assistant": ...}, ...]
        turns = [t for t in data if isinstance(t, dict) and "user" in t and "assistant" in t]
        return "", turns

    # 2) 旧版 \\n===\\n 分隔文本
    return "", _parse_separator_text(trimmed)


def _parse_separator_text(raw: str) -> list[dict]:
    """解析旧版 \\n===\\n 分隔的会话文本。对照现有 _update_session_memory 兼容逻辑。"""
    turns = []
    for turn_text in raw.split("\n===\n"):
        turn_text = turn_text.strip()
        if not turn_text:
            continue
        if "助手：" in turn_text:
            parts = turn_text.split("助手：", 1)
            u_part = parts[0].replace("用户：", "").strip()
            a_part = parts[1].strip()
            if u_part or a_part:
                turns.append({"user": u_part, "assistant": a_part})
    return turns


# ── 核心载荷构建（纯函数）────────────────────────────────────────────


def build_memory_payload(
    raw: str,
    new_turn: dict,
    *,
    max_turns: int,
    keep_recent: int,
    summarizer,
) -> dict:
    """
    合并当前轮、超阈值则把较旧 turns 交 summarizer 压缩。

    🎯 对照 ragent：
        - JdbcConversationMemorySummaryService.doCompressIfNeeded：超 triggerTurns 时取
          较旧消息 → LLM 摘要 → 存 summary 记录。
        - DefaultConversationMemoryService.load：摘要 + 最近窗口合并。

    Args:
        raw: SessionMemory.summary 原始文本（三种格式兼容）
        new_turn: {"user": str, "assistant": str}
        max_turns: 超过此轮数触发摘要压缩
        keep_recent: 压缩后保留的最近轮数
        summarizer: callable(older_turns: list[dict], existing_summary: str) -> str
                    抛异常时降级为保留 existing_summary

    Returns:
        {"summary": str, "turns": list[dict]}  — 可直接 json.dumps 存入 DB。
    """
    summary, turns = parse_memory(raw)
    turns = turns + [new_turn]

    if len(turns) <= max_turns:
        payload = {"summary": summary, "turns": turns}
        _truncate_assistant_if_needed(payload)
        return payload

    # 超出阈值：取较旧的 turns 交 summarizer 压缩
    older = turns[:-keep_recent]
    recent = turns[-keep_recent:]

    try:
        new_summary = summarizer(older, summary) or summary
    except Exception:
        logger.warning("记忆摘要生成失败，降级保留旧摘要。", exc_info=True)
        new_summary = summary

    payload = {"summary": new_summary, "turns": recent}
    _truncate_assistant_if_needed(payload)
    return payload


def _truncate_assistant_if_needed(payload: dict) -> None:
    """
    🛡️ 大响应截断保护。对照现有的 >2000 字节检查逻辑：
    如果 serialized payload 字节超限，截断 assistant 文本到 500 字符防止塞爆上下文。
    """
    serialized = json.dumps(payload, ensure_ascii=False)
    if len(serialized) > 2000:
        for turn in payload.get("turns", []):
            assistant_text = turn.get("assistant", "")
            if isinstance(assistant_text, str) and len(assistant_text) > 500:
                turn["assistant"] = assistant_text[:500] + "...(此回答过长已截断)..."


# ── LLM 摘要器 ────────────────────────────────────────────────────────


def _build_summary_messages(
    older_turns: list[dict],
    existing_summary: str,
    *,
    max_chars: int,
) -> list[dict]:
    """
    构造摘要 LLM 调用的消息列表。

    🎯 对照 ragent JdbcConversationMemorySummaryService.summarizeMessages：
        system prompt → 历史摘要（如有，作为 assistant 消息）→ 待压缩 turns → user 指令。
    """
    system = (
        "你是一个对话摘要压缩器。把以下多轮对话压成简洁的中文要点摘要，"
        "保留事实、决定、用户偏好。若已有历史摘要，则在此基础上合并去重、更新补充，"
        "不得将历史摘要当作新增事实来源，若与本轮冲突以本轮为准。"
        f"输出一段紧凑的摘要文本（严格≤{max_chars}字符），不要分段，不要列出轮次。"
    )
    messages: list[dict] = [{"role": "system", "content": system}]

    if existing_summary.strip():
        messages.append({
            "role": "assistant",
            "content": (
                "历史摘要（仅用于合并去重，不得作为事实新增来源；若与本轮对话冲突，以本轮对话为准）：\n"
                + existing_summary.strip()
            ),
        })

    # 把 older_turns 逐条转为 user/assistant 消息
    for turn in older_turns:
        user_text = (turn.get("user") or "").strip()
        assistant_text = (turn.get("assistant") or "").strip()
        if user_text:
            messages.append({"role": "user", "content": user_text})
        if assistant_text:
            messages.append({"role": "assistant", "content": assistant_text})

    messages.append({
        "role": "user",
        "content": (
            f"合并以上对话与历史摘要，去重后输出更新摘要。要求：严格≤{max_chars}字符；仅一行。"
        ),
    })
    return messages


def summarize_turns(
    provider,
    *,
    older_turns: list[dict],
    existing_summary: str,
    config: dict,
    runtime_config: dict | None = None,
) -> str:
    """
    调用 LLM 对较旧对话轮次生成摘要。

    🎯 严格仿 core/services/query_understanding.py:analyze 的模式：
        provider.chat(messages, temperature=0, runtime_config=...)
        任何异常都降级保留 existingSummary，绝不抛、绝不丢摘要。

    Args:
        provider: 具有 .chat(messages, model, temperature, runtime_config) → ChatResponse 的对象
        older_turns: 待压缩的较旧对话轮次
        existing_summary: 已有摘要（增量合并用）
        config: 含 enabled, summary_max_chars, model 等
        runtime_config: 透传（用户模型覆盖等）

    Returns:
        摘要文本；异常/空响应时返回 existing_summary。
    """
    if not config.get("enabled", True) or not older_turns:
        return existing_summary

    try:
        max_chars = int(config.get("summary_max_chars", 800))
        messages = _build_summary_messages(
            older_turns,
            existing_summary,
            max_chars=max_chars,
        )
        resp = provider.chat(
            messages,
            model=config.get("model"),
            temperature=0.0,
            runtime_config=runtime_config,
        )
        text = (resp.content or "").strip()
        if not text:
            return existing_summary
        return text[:max_chars] if len(text) > max_chars else text
    except Exception:
        logger.warning("对话记忆摘要 LLM 调用失败，降级保留旧摘要。", exc_info=True)
        return existing_summary
