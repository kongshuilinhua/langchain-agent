import json
import os
import uuid
from datetime import datetime

from utils.path_tool import get_abs_path


SESSION_STORE_PATH = get_abs_path("storage/chat_sessions.json")


def _ensure_store_dir() -> None:
    """确保会话持久化目录存在。"""
    os.makedirs(os.path.dirname(SESSION_STORE_PATH), exist_ok=True)


def _now() -> str:
    """统一生成 ISO 格式时间，方便排序和调试。"""
    return datetime.now().isoformat(timespec="seconds")


def _session_title_from_messages(messages: list[dict]) -> str:
    """用第一条用户消息生成会话标题，避免侧边栏全是“新对话”。"""
    for message in messages:
        if message.get("role") == "user":
            content = (message.get("content") or "").strip()
            if content:
                return content[:24] + ("..." if len(content) > 24 else "")
    return "新对话"


def load_sessions() -> list[dict]:
    """从本地 JSON 文件读取全部历史会话。"""
    _ensure_store_dir()
    if not os.path.exists(SESSION_STORE_PATH):
        return []

    with open(SESSION_STORE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    return data


def save_sessions(sessions: list[dict]) -> None:
    """把当前会话列表整体写回本地。"""
    _ensure_store_dir()
    with open(SESSION_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


def create_session(title: str = "新对话") -> dict:
    """创建一个新的空会话对象。"""
    now = _now()
    return {
        "id": uuid.uuid4().hex,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }


def upsert_session(sessions: list[dict], session: dict) -> list[dict]:
    """按 session_id 更新或插入会话。"""
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
    """按最近更新时间倒序排列，最新会话放最上面。"""
    return sorted(sessions, key=lambda item: item.get("updated_at", ""), reverse=True)


def update_session_messages(session: dict, messages: list[dict]) -> dict:
    """在保留元信息的前提下，刷新会话消息和标题。"""
    updated = dict(session)
    updated["messages"] = messages
    updated["updated_at"] = _now()
    updated["title"] = _session_title_from_messages(messages)
    return updated


def delete_session(sessions: list[dict], session_id: str) -> list[dict]:
    """删除指定会话。"""
    return [session for session in sessions if session["id"] != session_id]
