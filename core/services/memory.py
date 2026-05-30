from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from core.db.models import AgentMemoryProfile


MAX_MEMORY_SUMMARY_CHARS = 4000
MAX_MEMORY_FACTS = 50


def default_memory_profile_payload(agent_id: int) -> dict:
    return {
        "agent_id": agent_id,
        "enabled": False,
        "summary": "",
        "facts": [],
        "preferences": {},
        "updated_at": None,
    }


def memory_profile_payload(profile: AgentMemoryProfile | None, *, agent_id: int | None = None) -> dict:
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
    profile.updated_at = datetime.utcnow()
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
    profile = get_memory_profile(db, workspace_id=workspace_id, user_id=user_id, agent_id=agent_id)
    if not profile:
        return False
    db.delete(profile)
    db.commit()
    return True


def memory_used_event(profile: AgentMemoryProfile | None, *, session_summary_used: bool) -> dict:
    return {
        "enabled": bool(profile.enabled) if profile else False,
        "profile_found": bool(profile),
        "summary_used": bool(profile and profile.enabled and (profile.summary or "").strip()),
        "facts_count": len(normalize_facts(profile.facts)) if profile and profile.enabled else 0,
        "preferences_keys": sorted(normalize_preferences(profile.preferences).keys()) if profile and profile.enabled else [],
        "session_summary_used": bool(session_summary_used),
    }


def format_profile_memory(profile: AgentMemoryProfile | None) -> str:
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
    return str(value or "").strip()[:MAX_MEMORY_SUMMARY_CHARS]


def normalize_facts(value) -> list[str]:
    if not isinstance(value, list):
        return []
    facts = []
    for item in value:
        text = str(item or "").strip()
        if text:
            facts.append(text)
    return facts[:MAX_MEMORY_FACTS]


def normalize_preferences(value) -> dict:
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
