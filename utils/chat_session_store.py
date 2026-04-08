import json
import os
import uuid
from datetime import datetime

from utils.path_tool import get_abs_path


SESSION_STORE_PATH = get_abs_path("storage/chat_sessions.json")


def _ensure_store_dir() -> None:
    os.makedirs(os.path.dirname(SESSION_STORE_PATH), exist_ok=True)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _session_title_from_messages(messages: list[dict]) -> str:
    for message in messages:
        if message.get("role") == "user":
            content = (message.get("content") or "").strip()
            if content:
                return content[:24] + ("..." if len(content) > 24 else "")
    return "新对话"


def load_sessions() -> list[dict]:
    _ensure_store_dir()
    if not os.path.exists(SESSION_STORE_PATH):
        return []

    with open(SESSION_STORE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    return data


def save_sessions(sessions: list[dict]) -> None:
    _ensure_store_dir()
    with open(SESSION_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


def create_session(title: str = "新对话") -> dict:
    now = _now()
    return {
        "id": uuid.uuid4().hex,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }


def upsert_session(sessions: list[dict], session: dict) -> list[dict]:
    updated = []
    found = False
    for item in sessions:
        if item["id"] == session["id"]:
            updated.append(session)
            found = True
        else:
            updated.append(item)
    if not found:
        updated.append(session)
    return updated


def sort_sessions(sessions: list[dict]) -> list[dict]:
    return sorted(sessions, key=lambda item: item.get("updated_at", ""), reverse=True)


def update_session_messages(session: dict, messages: list[dict]) -> dict:
    updated = dict(session)
    updated["messages"] = messages
    updated["updated_at"] = _now()
    updated["title"] = _session_title_from_messages(messages)
    return updated


def delete_session(sessions: list[dict], session_id: str) -> list[dict]:
    return [session for session in sessions if session["id"] != session_id]
