from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from core.db.models import AgentMemoryProfile

# 🧠 魔鬼数字限制：
# 长效记忆摘要字符上限 4000 字，事实条目限制最多 50 条。
# 意图说明：长效记忆如果过长，在被拼入 System Prompt 后会喧宾夺主，挤占大模型宝贵的上下文空间，因此必须在此前置截断。
MAX_MEMORY_SUMMARY_CHARS = 4000
MAX_MEMORY_FACTS = 50


def default_memory_profile_payload(agent_id: int) -> dict:
    """默认空的长效记忆传输载荷（DTO）。"""
    return {
        "agent_id": agent_id,
        "enabled": False,
        "summary": "",
        "facts": [],
        "preferences": {},
        "updated_at": None,
    }


def memory_profile_payload(profile: AgentMemoryProfile | None, *, agent_id: int | None = None) -> dict:
    """将 ORM Profile 转换为标准的 API 传输 Payload，当不存在 profile 时返回预设默认空格式。"""
    if not profile:
        if agent_id is None:
            raise ValueError("agent_id is required for a default memory profile payload")
        return default_memory_profile_payload(agent_id)
    return {
        "agent_id": profile.agent_id,
        "enabled": bool(profile.enabled),
        "summary": profile.summary or "",
        "facts": normalize_facts(profile.facts),
        "preferences": normalize_preferences(profile.preferences),
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def get_memory_profile(
    db: Session,
    *,
    workspace_id: int,
    user_id: int,
    agent_id: int,
) -> AgentMemoryProfile | None:
    """
    租户隔离级拉取长效记忆档案。
    🛡️ 水平越权防线：强制绑定 `workspace_id` 与 `user_id`，防止跨用户非法读取记忆。
    """
    return (
        db.query(AgentMemoryProfile)
        .filter(
            AgentMemoryProfile.workspace_id == workspace_id,
            AgentMemoryProfile.user_id == user_id,
            AgentMemoryProfile.agent_id == agent_id,
        )
        .first()
    )


def upsert_memory_profile(
    db: Session,
    *,
    workspace_id: int,
    user_id: int,
    agent_id: int,
    payload: dict,
) -> AgentMemoryProfile:
    """
    更新或创建长效记忆档案。
    """
    profile = get_memory_profile(db, workspace_id=workspace_id, user_id=user_id, agent_id=agent_id)
    if not profile:
        profile = AgentMemoryProfile(
            workspace_id=workspace_id,
            user_id=user_id,
            agent_id=agent_id,
        )
        db.add(profile)

    if "enabled" in payload:
        profile.enabled = bool(payload["enabled"])
    if "summary" in payload:
        profile.summary = normalize_summary(payload["summary"])
    if "facts" in payload:
        profile.facts = normalize_facts(payload["facts"])
    if "preferences" in payload:
        profile.preferences = normalize_preferences(payload["preferences"])
    profile.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(profile)
    return profile


def delete_memory_profile(
    db: Session,
    *,
    workspace_id: int,
    user_id: int,
    agent_id: int,
) -> bool:
    """
    彻底物理擦除记忆档案。
    """
    profile = get_memory_profile(db, workspace_id=workspace_id, user_id=user_id, agent_id=agent_id)
    if not profile:
        return False
    db.delete(profile)
    db.commit()
    return True


def memory_used_event(profile: AgentMemoryProfile | None, *, session_summary_used: bool) -> dict:
    """生成高级 Trace 看板中关于“长短期记忆使用指标”的事件包。"""
    return {
        "enabled": bool(profile.enabled) if profile else False,
        "profile_found": bool(profile),
        "summary_used": bool(profile and profile.enabled and (profile.summary or "").strip()),
        "facts_count": len(normalize_facts(profile.facts)) if profile and profile.enabled else 0,
        "preferences_keys": sorted(normalize_preferences(profile.preferences).keys()) if profile and profile.enabled else [],
        "session_summary_used": bool(session_summary_used),
    }


def format_profile_memory(profile: AgentMemoryProfile | None) -> str:
    """
    将用户的长效记忆（长期摘要、事实列表、特征偏好）格式化拼接为平底纯文本，
    以便下游在 `workflow.py` 拼接并塞入 System Prompt 的上下文。
    """
    if not profile or not profile.enabled:
        return ""
    parts = []
    summary = (profile.summary or "").strip()
    if summary:
        parts.append(f"Long-term memory summary:\n{summary}")
    facts = normalize_facts(profile.facts)
    if facts:
        parts.append("Long-term memory facts:\n" + "\n".join(f"- {item}" for item in facts))
    preferences = normalize_preferences(profile.preferences)
    if preferences:
        lines = [f"- {key}: {value}" for key, value in sorted(preferences.items())]
        parts.append("Long-term memory preferences:\n" + "\n".join(lines))
    return "\n\n".join(parts)


def normalize_summary(value) -> str:
    """规整并严格截断长效记忆摘要。"""
    return str(value or "").strip()[:MAX_MEMORY_SUMMARY_CHARS]


def normalize_facts(value) -> list[str]:
    """规整并截断长效事实条数。"""
    if not isinstance(value, list):
        return []
    facts = []
    for item in value:
        text = str(item or "").strip()
        if text:
            facts.append(text)
    return facts[:MAX_MEMORY_FACTS]


def normalize_preferences(value) -> dict:
    """
    🛡️ 强数据清洗校验：
        规整用户偏好键值对（KV），剔除空白 Key 和无效 Value，只保留合法的字符串、整型、浮点型和布尔值等基本类型。
        防止嵌套的 JSON 或非法二进制注入数据库。
    """
    if not isinstance(value, dict):
        return {}
    normalized = {}
    for key, raw_value in value.items():
        clean_key = str(key or "").strip()
        if not clean_key:
            continue
        clean_value = normalize_preference_value(raw_value)
        if clean_value is not None:
            normalized[clean_key] = clean_value
    return normalized


def normalize_preference_value(value):
    """
    防御性的偏好值类型限定过滤器。
    仅接纳 Python 基础标量数据类型及基础列表。
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        normalized = []
        for item in value:
            if isinstance(item, (str, int, float, bool)):
                normalized.append(item)
        return normalized
    return None
