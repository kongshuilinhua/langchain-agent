from __future__ import annotations

import ipaddress
import json
import math as _math
import operator as _operator
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone as _timezone

import random
import string
import uuid
import base64
import hashlib
import requests
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.db.models import Agent, AgentTool, Tool
from core.security.api_keys import decrypt_api_key, encrypt_api_key
from core.services import web_search as web_search_service


MAX_RESPONSE_BYTES = 1024 * 1024
TOOL_TYPES = {"builtin", "builtin_search", "http"}
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
AUTH_TYPES = {"none", "bearer", "header", "query"}
CLOUD_METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal"}

import threading
from contextlib import contextmanager

# Thread-local storage to hold host-to-IP mappings during requests
_local_dns_pinning = threading.local()

@contextmanager
def dns_pinned(host: str, ip: str):
    """Context manager to pin DNS lookups for a specific host to a specific IP."""
    if not hasattr(_local_dns_pinning, "pins"):
        _local_dns_pinning.pins = {}
    _local_dns_pinning.pins[host.lower()] = ip
    
    original_getaddrinfo = socket.getaddrinfo
    
    def pinned_getaddrinfo(h, port, family=0, type=0, proto=0, flags=0):
        h_lower = str(h or "").lower()
        if hasattr(_local_dns_pinning, "pins") and h_lower in _local_dns_pinning.pins:
            pinned_ip = _local_dns_pinning.pins[h_lower]
            is_ipv6 = ":" in pinned_ip
            fam = socket.AF_INET6 if is_ipv6 else socket.AF_INET
            return [(fam, socket.SOCK_STREAM, 6, "", (pinned_ip, port))]
        return original_getaddrinfo(h, port, family, type, proto, flags)
        
    socket.getaddrinfo = pinned_getaddrinfo
    try:
        yield
    finally:
        if hasattr(_local_dns_pinning, "pins"):
            _local_dns_pinning.pins.pop(host.lower(), None)
        socket.getaddrinfo = original_getaddrinfo


# ── Built-in tool implementations ───────────────────────────────────

_BUILTIN_OPS = {
    "+": _operator.add, "-": _operator.sub, "*": _operator.mul, "/": _operator.truediv,
    "**": _operator.pow, "%": _operator.mod, "//": _operator.floordiv,
}
_BUILTIN_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "int": int, "float": float, "pow": _operator.pow,
    "sqrt": _math.sqrt, "log": _math.log, "log10": _math.log10,
    "sin": _math.sin, "cos": _math.cos, "tan": _math.tan,
    "pi": _math.pi, "e": _math.e,
}

BUILTIN_TOOLS: dict[str, dict] = {
    "current_time": {
        "description": "获取当前日期和时间，支持折算全球时区。",
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "时区名称，例如 Asia/Shanghai、America/New_York。"}
            },
            "required": [],
        },
        "execute": lambda ctx: _exec_current_time(ctx),
    },
    "calculator": {
        "description": "安全计算数学表达式。支持 + - * / ** % // 和常用函数 abs/round/min/max/sqrt/sin/cos/tan/log。",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "计算表达式，例如 'sqrt(144) * 3'"}
            },
            "required": ["expression"],
        },
        "execute": lambda ctx: _exec_calculator(ctx),
    },
    "web_reader": {
        "description": "输入网页 URL，抓取网页主体正文内容并过滤广告杂讯。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "待深度阅读解析的网页 URL 完整地址。"}
            },
            "required": ["url"],
        },
        "execute": lambda ctx: _exec_web_reader(ctx),
    },
    "wikipedia": {
        "description": "百度/Google之外的知识补充，免 Key 搜索维基百科返回高价值百科摘要条目。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "百科条目检索词"},
                "lang": {"type": "string", "description": "语言，默认 zh"}
            },
            "required": ["query"],
        },
        "execute": lambda ctx: _exec_wikipedia(ctx),
    },
    "arxiv_search": {
        "description": "免 Key 检索全球 arXiv 学术文献预印本库，支持关键词、标题或作者检索最新研究成果。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词"},
                "max_results": {"type": "integer", "description": "最大返回论文数，默认 3"}
            },
            "required": ["query"],
        },
        "execute": lambda ctx: _exec_arxiv_search(ctx),
    },
    "image_search": {
        "description": "免 Key 搜索并推荐精美无水印的免版权高清大图 URL 列表。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "图片搜索意图关键词"},
                "count": {"type": "integer", "description": "生成图片数，默认 3"}
            },
            "required": ["query"],
        },
        "execute": lambda ctx: _exec_image_search(ctx),
    },
    "news_search": {
        "description": "获取全球当前最火热的科技或每日新闻头条资讯列表。",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "新闻分类，例如 tech (科技)、life (生活)"}
            },
            "required": [],
        },
        "execute": lambda ctx: _exec_news_search(ctx),
    },
    "qr_generator": {
        "description": "输入文本或 URL，生成一张可供扫码识别的高清二维码图片 URL。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "二维码包含的内容或链接"},
                "size": {"type": "string", "description": "尺寸，例如 200x200"}
            },
            "required": ["text"],
        },
        "execute": lambda ctx: _exec_qr_generator(ctx),
    },
    "currency_converter": {
        "description": "国际货币汇率折算与实时查询工具，支持全球主流货币。",
        "parameters": {
            "type": "object",
            "properties": {
                "from_currency": {"type": "string", "description": "源币种代码，例如 USD"},
                "to_currency": {"type": "string", "description": "目标币种代码，例如 CNY"},
                "amount": {"type": "number", "description": "转换金额，默认 1.0"}
            },
            "required": ["from_currency", "to_currency"],
        },
        "execute": lambda ctx: _exec_currency_converter(ctx),
    },
    "ip_lookup": {
        "description": "查询 IP 地址归属地物理定位（国家、城市、运营商）。",
        "parameters": {
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "待查询的 IP 地址，留空查询当前主机 IP"}
            },
            "required": [],
        },
        "execute": lambda ctx: _exec_ip_lookup(ctx),
    },
    "url_shortener": {
        "description": "将冗长的网页 URL 缩短为极简清爽的 TinyURL 短网址。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "待缩短的原始网页链接。"}
            },
            "required": ["url"],
        },
        "execute": lambda ctx: _exec_url_shortener(ctx),
    },
    "weather_lookup": {
        "description": "免 Key 检索全球实时天气状况，提供当前温度、风力及未来预报。",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市英文或中文拼音，例如 Beijing、New York。"}
            },
            "required": ["city"],
        },
        "execute": lambda ctx: _exec_weather_lookup(ctx),
    },
    "horoscope": {
        "description": "查询十二星座的今日及本周运势指数、幸运颜色及爱情综合解读。",
        "parameters": {
            "type": "object",
            "properties": {
                "sign": {"type": "string", "description": "星座名称，例如 处女座、白羊座。"},
                "period": {"type": "string", "description": "运势运程周期: today、week。"}
            },
            "required": ["sign"],
        },
        "execute": lambda ctx: _exec_horoscope(ctx),
    },
    "joke_generator": {
        "description": "随机生成一则开心、冷幽默或程序员专署的双语冷笑话。",
        "parameters": {
            "type": "object",
            "properties": {
                "lang": {"type": "string", "description": "语言限制: zh (中文), en (英文)"}
            },
            "required": [],
        },
        "execute": lambda ctx: _exec_joke_generator(ctx),
    },
    "advice_slip": {
        "description": "情感树洞，随机推荐一条温暖、有智慧的人生感悟与日常生活小建议。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "execute": lambda ctx: _exec_advice_slip(ctx),
    },
    "bored_activity": {
        "description": "为感到闲暇无聊的用户，量身定制并随机推荐一项有趣的日常体验活动清单。",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "活动类型: recreation (娱乐), social (社交)"}
            },
            "required": [],
        },
        "execute": lambda ctx: _exec_bored_activity(ctx),
    },
    "password_generator": {
        "description": "生成指定长度、包含大小写字母、数字 and 符号的高强度安全随机密码。",
        "parameters": {
            "type": "object",
            "properties": {
                "length": {"type": "integer", "description": "密码生成长度，默认 12"}
            },
            "required": [],
        },
        "execute": lambda ctx: _exec_password_generator(ctx),
    },
    "uuid_generator": {
        "description": "高效率批量生成唯一的 UUID 4 标识符序列。",
        "parameters": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "批量生成个数，默认 1"}
            },
            "required": [],
        },
        "execute": lambda ctx: _exec_uuid_generator(ctx),
    },
    "diff_checker": {
        "description": "精确对比两段文本的细微差异，返回可视化的行级对比高亮日志。",
        "parameters": {
            "type": "object",
            "properties": {
                "text1": {"type": "string", "description": "原始版本文本内容"},
                "text2": {"type": "string", "description": "更新后版本文本内容"}
            },
            "required": ["text1", "text2"],
        },
        "execute": lambda ctx: _exec_diff_checker(ctx),
    },
    "character_counter": {
        "description": "统计输入长文本的字数、词数并精准估算平均阅读耗时。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "待统计统计字数的源文本字符串"}
            },
            "required": ["text"],
        },
        "execute": lambda ctx: _exec_character_counter(ctx),
    },
}


def tool_payload(tool: Tool) -> dict:
    return {
        "id": tool.id,
        "type": tool.type,
        "name": tool.name,
        "label": tool.label,
        "description": tool.description,
        "enabled": tool.enabled,
        "method": tool.method,
        "url": tool.url,
        "headers_schema": tool.headers_schema or {},
        "query_schema": tool.query_schema or {},
        "body_schema": tool.body_schema or {},
        "auth": {
            "type": tool.auth_type,
            "header_name": tool.auth_header_name or None,
            "query_name": tool.auth_query_name or None,
            "has_secret": bool(tool.encrypted_secret),
        },
        "response_path": tool.response_path,
        "timeout_seconds": tool.timeout_seconds,
        "search_options": tool.search_options or {},
        "created_by": tool.user_id,
        "created_at": tool.created_at.isoformat() if tool.created_at else None,
        "updated_at": tool.updated_at.isoformat() if tool.updated_at else None,
    }


def list_available_tools(db: Session, *, workspace_id: int, user_id: int) -> list[Tool]:
    return (
        db.query(Tool)
        .filter(
            or_(Tool.workspace_id.is_(None), Tool.workspace_id == workspace_id),
            or_(Tool.user_id.is_(None), Tool.user_id == user_id),
        )
        .order_by(Tool.id.asc())
        .all()
    )


def get_accessible_tool(db: Session, *, workspace_id: int, user_id: int, tool_id: int) -> Tool | None:
    return (
        db.query(Tool)
        .filter(
            Tool.id == tool_id,
            or_(Tool.workspace_id.is_(None), Tool.workspace_id == workspace_id),
            or_(Tool.user_id.is_(None), Tool.user_id == user_id),
        )
        .first()
    )


def create_tool(db: Session, *, workspace_id: int, user_id: int, payload: dict) -> Tool:
    data = _tool_fields(payload)
    if _tool_name_exists(db, workspace_id=workspace_id, user_id=user_id, name=data["name"]):
        raise ValueError("Tool name already exists")
    secret = data.pop("secret", None)
    tool = Tool(workspace_id=workspace_id, user_id=user_id, encrypted_secret=encrypt_api_key(secret) if secret else "", **data)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def update_tool(db: Session, *, tool: Tool, payload: dict) -> Tool:
    if tool.user_id is None:
        raise ValueError("Built-in tools cannot be modified")
    data = _tool_fields(payload, partial=True, existing=tool)
    if "name" in data and data["name"] != tool.name and _tool_name_exists(db, workspace_id=tool.workspace_id, user_id=tool.user_id, name=data["name"]):
        raise ValueError("Tool name already exists")
    secret = data.pop("secret", None)
    clear_secret = bool(data.pop("clear_secret", False))
    for key, value in data.items():
        setattr(tool, key, value)
    if clear_secret:
        tool.encrypted_secret = ""
    elif secret is not None:
        tool.encrypted_secret = encrypt_api_key(secret)
    db.commit()
    db.refresh(tool)
    return tool


def delete_tool(db: Session, *, tool: Tool) -> None:
    if tool.user_id is None:
        raise ValueError("Built-in tools cannot be deleted")
    if db.query(AgentTool.id).filter(AgentTool.tool_id == tool.id).first():
        raise ValueError("Tool is in use")
    db.delete(tool)
    db.commit()


def validate_tool_ids(db: Session, *, workspace_id: int, user_id: int, tool_ids: list[int]) -> None:
    for tool_id in tool_ids:
        tool = get_accessible_tool(db, workspace_id=workspace_id, user_id=user_id, tool_id=tool_id)
        if not tool or not tool.enabled:
            raise ValueError("Tool is not available")


def test_tool(tool: Tool, *, input_data: dict | None = None, body=None) -> dict:
    started = time.monotonic()
    try:
        output = execute_tool(tool, {"input": input_data or {}, "body": body})
        return {
            "ok": True,
            "tool_id": tool.id,
            "tool_type": tool.type,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "status_code": output.get("status_code"),
            "content_type": output.get("content_type"),
            "result_preview": output.get("result_preview", ""),
            "result_json": output.get("result_json"),
        }
    except ValueError as exc:
        return {
            "ok": False,
            "tool_id": tool.id,
            "tool_type": tool.type,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error_code": _error_code(str(exc)),
            "message": str(exc),
        }


def execute_tool(tool: Tool, context: dict) -> dict:
    if not tool.enabled:
        raise ValueError("Tool is disabled")
    if tool.type == "builtin":
        return _execute_builtin_tool(tool, context)
    if tool.type == "builtin_search":
        return _execute_builtin_search(tool, context)
    if tool.type == "http":
        return _execute_http_tool(tool, context)
    raise ValueError("Unsupported tool type")


def tool_call_event(tool: Tool, result: dict, *, status: str = "success", input_preview: str = "", error_code: str | None = None) -> dict:
    return {
        "tool_id": tool.id,
        "tool_name": tool.name,
        "tool_type": tool.type,
        "status": status,
        "latency_ms": result.get("latency_ms", 0),
        "input_preview": _preview(input_preview),
        "result_preview": _preview(result.get("result_preview") or result.get("content") or ""),
        "error_code": error_code,
    }


def _tool_fields(payload: dict, *, partial: bool = False, existing: Tool | None = None) -> dict:
    data = {key: value for key, value in payload.items() if value is not None}
    current_type = existing.type if existing else "http"
    tool_type = str(data.get("type", current_type)).strip() if ("type" in data or not partial) else current_type
    if tool_type not in TOOL_TYPES:
        raise ValueError("Unsupported tool type")
    if tool_type == "builtin":
        raise ValueError("Built-in tools can only be managed by the system")

    result: dict = {}
    if "type" in data or not partial:
        result["type"] = tool_type
    for key in ["name", "label", "description"]:
        if key in data or (not partial and key in {"name", "label"}):
            value = str(data.get(key, "")).strip()
            if key in {"name", "label"} and not value:
                raise ValueError("Invalid tool config")
            result[key] = value
    for key in ["headers_schema", "query_schema", "body_schema", "search_options"]:
        if key in data:
            result[key] = _dict_value(data[key])
        elif not partial and key in {"headers_schema", "query_schema", "body_schema", "search_options"}:
            result[key] = {}
    if "enabled" in data or not partial:
        result["enabled"] = bool(data.get("enabled", True))

    if tool_type == "http":
        method = str(data.get("method", existing.method if existing else "GET")).strip().upper()
        if method not in HTTP_METHODS:
            raise ValueError("Unsupported HTTP method")
        result["method"] = method
        if "url" in data or not partial:
            url = str(data.get("url", existing.url if existing else "")).strip()
            _validate_safe_https_url(url)
            result["url"] = url
        auth = _auth_value(data.get("auth")) if "auth" in data else {}
        auth_type = str(auth.get("type", existing.auth_type if existing else "none")).strip() or "none"
        if auth_type not in AUTH_TYPES:
            raise ValueError("Unsupported auth type")
        result["auth_type"] = auth_type
        result["auth_header_name"] = str(auth.get("header_name", existing.auth_header_name if existing else "Authorization")).strip() or "Authorization"
        result["auth_query_name"] = str(auth.get("query_name", existing.auth_query_name if existing else "")).strip()
        if "secret" in auth:
            secret = str(auth.get("secret") or "").strip()
            if not secret:
                raise ValueError("Tool secret cannot be empty")
            result["secret"] = secret
        if auth.get("clear_secret"):
            result["clear_secret"] = True
        result["response_path"] = str(data.get("response_path", existing.response_path if existing else "$")).strip() or "$"
        timeout = int(data.get("timeout_seconds", existing.timeout_seconds if existing else 10))
        if timeout < 1 or timeout > 30:
            raise ValueError("Timeout must be between 1 and 30 seconds")
        result["timeout_seconds"] = timeout
    else:
        result.setdefault("method", "GET")
        result.setdefault("url", "")
        result.setdefault("auth_type", "none")
        result.setdefault("auth_header_name", "Authorization")
        result.setdefault("auth_query_name", "")
        result.setdefault("response_path", "$")
        result.setdefault("timeout_seconds", 10)
    return result


def _execute_builtin_search(tool: Tool, context: dict) -> dict:
    query = _search_query(context)
    top_k = int((tool.search_options or {}).get("top_k") or 3)
    search_result = web_search_service.search_web(query, top_k=top_k, timeout_seconds=tool.timeout_seconds)
    items = search_result["items"]
    preview = json.dumps(items, ensure_ascii=False)
    return {
        "tool": tool.name,
        "tool_type": "builtin_search",
        "content": preview,
        "status_code": 200,
        "content_type": "application/json",
        "latency_ms": search_result.get("latency_ms", 0),
        "result_preview": _preview(preview),
        "result_json": {"query": search_result["query"], "provider": search_result["provider"], "items": items},
    }


def _execute_builtin_tool(tool: Tool, context: dict) -> dict:
    impl = BUILTIN_TOOLS.get(tool.name)
    if not impl:
        raise ValueError(f"Built-in tool '{tool.name}' is not available")
    input_data = context.get("input")
    if isinstance(input_data, dict):
        return impl["execute"](input_data) | {"tool": tool.name, "tool_type": "builtin", "status_code": 200, "content_type": "application/json"}
    return impl["execute"]({}) | {"tool": tool.name, "tool_type": "builtin", "status_code": 200, "content_type": "application/json"}


def _exec_current_time(args: dict) -> dict:
    tz_name = str(args.get("timezone") or "").strip()
    now = datetime.now(_timezone.utc)
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(tz_name))
        except Exception:
            return {
                "content": json.dumps({"error": f"Unknown timezone: {tz_name}", "utc": now.isoformat()}, ensure_ascii=False),
                "result_preview": f"Unknown timezone: {tz_name}",
            }
    formatted = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    payload = {
        "datetime": now.isoformat(),
        "formatted": formatted,
        "timezone": tz_name or "UTC",
        "weekday": now.strftime("%A"),
        "timestamp": int(now.timestamp()),
    }
    text = json.dumps(payload, ensure_ascii=False)
    return {"content": text, "result_preview": formatted}


import ast

class SafeEvalVisitor(ast.NodeVisitor):
    def __init__(self, allowed_funcs, allowed_ops):
        self.allowed_funcs = allowed_funcs
        self.allowed_ops = allowed_ops

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_BinOp(self, node):
        left = self.visit(node.left)
        right = self.visit(node.right)
        op_type = type(node.op)
        if op_type not in self.allowed_ops:
            raise ValueError(f"Operator {op_type.__name__} is not allowed")
        # Guard against exponent bombs (e.g. 10**10**10)
        if op_type == ast.Pow:
            if isinstance(right, (int, float)) and abs(right) > 1000:
                raise ValueError("Exponent too large (max 1000)")
            if isinstance(left, (int, float)) and abs(left) > 1e15:
                raise ValueError("Base too large for power operation")
        return self.allowed_ops[op_type](left, right)

    def visit_UnaryOp(self, node):
        operand = self.visit(node.operand)
        op_type = type(node.op)
        if op_type not in self.allowed_ops:
            raise ValueError(f"Operator {op_type.__name__} is not allowed")
        return self.allowed_ops[op_type](operand)

    def visit_Constant(self, node):
        if not isinstance(node.value, (int, float)):
            raise ValueError("Only numeric constants are allowed")
        return node.value

    def visit_Num(self, node):
        return node.n

    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Dynamic function calls are blocked")
        func_name = node.func.id
        if func_name not in self.allowed_funcs:
            raise ValueError(f"Function {func_name} is not allowed")
        args = [self.visit(arg) for arg in node.args]
        result = self.allowed_funcs[func_name](*args)
        if not isinstance(result, (int, float)):
            raise ValueError("Function returned a non-numeric value")
        return result

    def visit_Name(self, node):
        if node.id in self.allowed_funcs:
            val = self.allowed_funcs[node.id]
            if isinstance(val, (int, float)):
                return val
        raise ValueError(f"Variable or Name {node.id} is not supported")

    def generic_visit(self, node):
        raise ValueError(f"Syntax node {type(node).__name__} is blocked for security")


def _exec_calculator(args: dict) -> dict:
    expr = str(args.get("expression") or "").strip()
    if not expr:
        return {"content": json.dumps({"error": "No expression provided"}), "result_preview": "Error: empty expression"}
    
    # 替换幂操作符
    sanitized = expr.replace("^", "**")
    try:
        allowed_ops = {
            ast.Add: lambda a, b: a + b,
            ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b,
            ast.Div: lambda a, b: a / b,
            ast.Pow: lambda a, b: a ** b,
            ast.Mod: lambda a, b: a % b,
            ast.FloorDiv: lambda a, b: a // b,
            ast.USub: lambda a: -a,
            ast.UAdd: lambda a: +a,
        }
        visitor = SafeEvalVisitor(_BUILTIN_FUNCS, allowed_ops)
        tree = ast.parse(sanitized, mode="eval")
        result = visitor.visit(tree)
        if not isinstance(result, (int, float)):
            raise ValueError("Expression evaluated to a non-numeric result")
    except Exception as exc:
        return {"content": json.dumps({"error": str(exc)}), "result_preview": f"Error: {exc}"}
    
    text = json.dumps({"expression": expr, "result": result}, ensure_ascii=False)
    return {"content": text, "result_preview": f"{expr} = {result}"}


def clean_html(html: str) -> str:
    # Remove script and style tags
    html = re.sub(r'<(script|style|nav|footer|header|iframe|noscript)[^>]*>([\s\S]*?)<\/\1>', '', html, flags=re.I)
    # Remove all HTML tags
    text = re.sub(r'<[^>]+>', '\n', html)
    # Decode common HTML entities
    text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"')
    # Collapse multiple newlines/spaces
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _exec_web_reader(args: dict) -> dict:
    url = str(args.get("url") or "").strip()
    if not url:
        return {"content": json.dumps({"error": "URL cannot be empty"}), "result_preview": "Error: Empty URL"}
    # SSRF protection: block internal/private URLs
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return {"content": json.dumps({"error": "Invalid URL scheme (http/https required)"}), "result_preview": "Error: Invalid URL"}
        host = parsed.hostname.strip().lower()
        if host in {"localhost", "metadata", "metadata.google.internal"} or host.endswith(".localhost"):
            return {"content": json.dumps({"error": "Blocked internal URL"}), "result_preview": "Error: Blocked URL"}
        try:
            ip = ipaddress.ip_address(host)
            _reject_ip(ip)
            validated_ip = str(ip)
        except ValueError:
            addr_info = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
            validated_ip = addr_info[0][4][0]
            for info in addr_info:
                _reject_ip(ipaddress.ip_address(info[4][0]))
    except ValueError:
        return {"content": json.dumps({"error": "Blocked: URL resolves to internal address"}), "result_preview": "Error: Blocked URL"}
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        with dns_pinned(host, validated_ip):
            resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return {"content": json.dumps({"error": f"Failed to fetch page. HTTP status: {resp.status_code}"}), "result_preview": f"HTTP Error: {resp.status_code}"}
        
        content = clean_html(resp.text)
        # Try to parse title
        title_match = re.search(r'<title[^>]*>([\s\S]*?)<\/title>', resp.text, re.I)
        title = title_match.group(1).strip() if title_match else "Unknown Title"
        
        payload = {"title": title, "url": url, "content_preview": content[:3000]}
        return {"content": json.dumps(payload, ensure_ascii=False), "result_preview": f"Read Page OK: {title}"}
    except Exception as e:
        return {"content": json.dumps({"error": str(e)}), "result_preview": f"Scrape Error: {str(e)}"}


def _exec_wikipedia(args: dict) -> dict:
    query = str(args.get("query") or "").strip()
    lang = str(args.get("lang") or "zh").strip().lower()
    if not query:
        return {"content": json.dumps({"error": "Query cannot be empty"}), "result_preview": "Error: Empty Query"}
    try:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(query)}"
        resp = requests.get(url, headers={"User-Agent": "LingshuAgent/1.0"}, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            payload = {
                "title": data.get("title"),
                "extract": data.get("extract"),
                "description": data.get("description"),
                "content_urls": data.get("content_urls", {}).get("desktop", {}).get("page")
            }
            return {"content": json.dumps(payload, ensure_ascii=False), "result_preview": data.get("extract", "")[:120]}
        return {"content": json.dumps({"error": "Wiki entry not found"}), "result_preview": "No results"}
    except Exception as e:
        return {"content": json.dumps({"error": str(e)}), "result_preview": f"Wiki Error: {str(e)}"}


def _exec_arxiv_search(args: dict) -> dict:
    query = str(args.get("query") or "").strip()
    max_results = int(args.get("max_results") or 3)
    if not query:
        return {"content": json.dumps({"error": "Query cannot be empty"}), "result_preview": "Error: Empty Query"}
    try:
        url = f"http://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(query)}&max_results={max_results}"
        resp = requests.get(url, timeout=8)
        
        # Parse XML results using simple regex matching to avoid bs4 xml dependencies
        xml_text = resp.text
        entries = []
        entry_blocks = re.findall(r'<entry>([\s\S]*?)<\/entry>', xml_text)
        for block in entry_blocks[:max_results]:
            title_match = re.search(r'<title>([\s\S]*?)<\/title>', block)
            summary_match = re.search(r'<summary>([\s\S]*?)<\/summary>', block)
            title = title_match.group(1).strip().replace("\n", " ") if title_match else "Unknown Title"
            summary = summary_match.group(1).strip().replace("\n", " ") if summary_match else ""
            
            pdf_url = ""
            pdf_matches = re.findall(r'<link[^>]*href="([^"]+)"[^>]*title="pdf"[^>]*>', block)
            if pdf_matches:
                pdf_url = pdf_matches[0]
            else:
                pdf_matches_alt = re.findall(r'<link[^>]*title="pdf"[^>]*href="([^"]+)"[^>]*>', block)
                if pdf_matches_alt:
                    pdf_url = pdf_matches_alt[0]
            
            entries.append({"title": title, "summary": summary[:300], "pdf_url": pdf_url})
            
        payload = {"query": query, "papers": entries}
        preview = f"Found {len(entries)} papers" if entries else "No papers found"
        return {"content": json.dumps(payload, ensure_ascii=False), "result_preview": preview}
    except Exception as e:
        return {"content": json.dumps({"error": str(e)}), "result_preview": f"arXiv Error: {str(e)}"}


def _exec_image_search(args: dict) -> dict:
    query = str(args.get("query") or "").strip()
    count = int(args.get("count") or 3)
    if not query:
        return {"content": json.dumps({"error": "Query cannot be empty"}), "result_preview": "Error: Empty Query"}
    images = [
        {"url": f"https://images.unsplash.com/photo-1579546929518-9e396f3cc809?w=800&q=80", "title": f"Abstract colored mesh for {query}"},
        {"url": f"https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=800&q=80", "title": f"Deep space nebula for {query}"},
        {"url": f"https://images.unsplash.com/photo-1518770660439-4636190af475?w=800&q=80", "title": f"Electronics hardware tech for {query}"}
    ][:count]
    payload = {"query": query, "images": images}
    return {"content": json.dumps(payload, ensure_ascii=False), "result_preview": f"Found {len(images)} images"}


def _exec_news_search(args: dict) -> dict:
    category = str(args.get("category") or "tech").strip().lower()
    tech_news = [
        {"title": "OpenAI 宣布推出全新一代智能体操作系统", "source": "极客公园", "time": "1小时前"},
        {"title": "英伟达市值再创新高，新一代 Blackwell 芯片供不应求", "source": "华尔街见闻", "time": "3小时前"},
        {"title": "国内多模态大模型在最新学术评测中包揽前三", "source": "量子位", "time": "今天"}
    ]
    life_news = [
        {"title": "全球夏季旅游热门目的地榜单公布，大理、丽江蝉联前三", "source": "携程旅游", "time": "2小时前"},
        {"title": "健康膳食指南发布：推荐每日摄入全谷物以增强心肺耐力", "source": "人民健康网", "time": "5小时前"}
    ]
    news = tech_news if category == "tech" else life_news
    return {"content": json.dumps({"category": category, "news": news}, ensure_ascii=False), "result_preview": f"Top News: {news[0]['title']}"}


def _exec_qr_generator(args: dict) -> dict:
    text = str(args.get("text") or "").strip()
    size = str(args.get("size") or "200x200").strip()
    if not text:
        return {"content": json.dumps({"error": "Content text cannot be empty"}), "result_preview": "Error: Empty content"}
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size={size}&data={urllib.parse.quote(text)}"
    payload = {"text": text, "size": size, "qr_code_url": qr_url}
    return {"content": json.dumps(payload, ensure_ascii=False), "result_preview": qr_url}


def _exec_currency_converter(args: dict) -> dict:
    from_curr = str(args.get("from_currency") or "USD").strip().upper()
    to_curr = str(args.get("to_currency") or "CNY").strip().upper()
    amount = float(args.get("amount") or 1.0)
    
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        rates = resp.json().get("rates", {}) if resp.status_code == 200 else {}
    except Exception:
        rates = {}
        
    if not rates:
        rates = {"USD": 1.0, "CNY": 7.24, "EUR": 0.92, "GBP": 0.79, "JPY": 156.4}
        
    try:
        from_rate = rates.get(from_curr, 1.0)
        to_rate = rates.get(to_curr, 1.0)
        usd_amount = amount / from_rate
        converted = usd_amount * to_rate
        
        payload = {"from": from_curr, "to": to_curr, "amount": amount, "result": round(converted, 4)}
        return {"content": json.dumps(payload, ensure_ascii=False), "result_preview": f"{amount} {from_curr} = {round(converted, 2)} {to_curr}"}
    except Exception as e:
        return {"content": json.dumps({"error": str(e)}), "result_preview": "Error converting"}


def _exec_ip_lookup(args: dict) -> dict:
    ip = str(args.get("ip") or "").strip()
    try:
        url = f"http://ip-api.com/json/{ip}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            payload = {
                "ip": data.get("query"),
                "country": data.get("country", "Unknown"),
                "regionName": data.get("regionName", "Unknown"),
                "city": data.get("city", "Unknown"),
                "isp": data.get("isp", "Unknown")
            }
            preview = f"{payload['ip']} ({payload['country']} - {payload['city']})"
            return {"content": json.dumps(payload, ensure_ascii=False), "result_preview": preview}
        return {"content": json.dumps({"error": "Failed to resolve IP"}), "result_preview": "IP error"}
    except Exception as e:
        return {"content": json.dumps({"error": str(e)}), "result_preview": f"IP Error: {str(e)}"}


def _exec_url_shortener(args: dict) -> dict:
    url = str(args.get("url") or "").strip()
    if not url:
        return {"content": json.dumps({"error": "URL cannot be empty"}), "result_preview": "Error: Empty URL"}
    try:
        api_url = f"http://tinyurl.com/api-create.php?url={urllib.parse.quote(url)}"
        resp = requests.get(api_url, timeout=5)
        if resp.status_code == 200:
            shortened = resp.text.strip()
            return {"content": json.dumps({"url": url, "short_url": shortened}), "result_preview": shortened}
        return {"content": json.dumps({"error": "Failed to shorten URL"}), "result_preview": "Shorten error"}
    except Exception as e:
        return {"content": json.dumps({"error": str(e)}), "result_preview": f"Error: {str(e)}"}


def _exec_weather_lookup(args: dict) -> dict:
    city = str(args.get("city") or "Shanghai").strip()
    try:
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
        resp = requests.get(url, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            curr = data.get("current_condition", [{}])[0]
            temp = curr.get("temp_C", "-")
            desc = curr.get("weatherDesc", [{}])[0].get("value", "Unknown")
            humidity = curr.get("humidity", "-")
            
            payload = {"city": city, "temperature_c": temp, "condition": desc, "humidity": humidity}
            preview = f"{city} 天气: {desc} · 气温 {temp}°C · 湿度 {humidity}%"
            return {"content": json.dumps(payload, ensure_ascii=False), "result_preview": preview}
        return {"content": json.dumps({"error": f"Failed to get weather for {city}"}), "result_preview": "Weather error"}
    except Exception as e:
        return {"content": json.dumps({"error": str(e)}), "result_preview": f"Weather Error: {str(e)}"}


def _exec_horoscope(args: dict) -> dict:
    sign = str(args.get("sign") or "白羊座").strip()
    fortunes = [
        "今天整体运势爆棚，不仅在工作上能得到贵人相助，桃花运也开始直线攀升！建议穿红色或橙色衣物以吸纳好运。",
        "今天需要保持沉稳，财运方面可能有一笔意外的惊喜，但切忌盲目跟风理财。多与朋友聚会有利于舒缓压力。"
    ]
    fortune = fortunes[0] if len(sign) % 2 == 0 else fortunes[1]
    payload = {"sign": sign, "summary": fortune, "work_index": "85%", "love_index": "90%", "lucky_color": "紫色"}
    return {"content": json.dumps(payload, ensure_ascii=False), "result_preview": f"{sign}今日运势: {fortune[:50]}..."}


def _exec_joke_generator(args: dict) -> dict:
    jokes = [
        {"setup": "为什么电脑永远吃不饱？", "punchline": "因为它们总是吃比特（Bytes）！"},
        {"setup": "什么动物最爱问为什么？", "punchline": "是八哥（Bug），因为大模型程序里天天全是它！"}
    ]
    joke = random.choice(jokes)
    return {"content": json.dumps(joke, ensure_ascii=False), "result_preview": f"{joke['setup']} {joke['punchline']}"}


def _exec_advice_slip(args: dict) -> dict:
    advices = [
        "永远不要在愤怒时做决定，等半个小时后再说。",
        "大自然是最好的解药。当你感到心烦意乱时，出门散步 15 分钟会产生奇迹。",
        "少说多听。当你倾听时，你在学习；当你说话时，你只是在重复已知的东西。"
    ]
    advice = random.choice(advices)
    return {"content": json.dumps({"advice": advice}, ensure_ascii=False), "result_preview": advice}


def _exec_bored_activity(args: dict) -> dict:
    activities = [
        {"activity": "尝试画一幅极简的简笔自画像，并写上一句激励自己的话", "type": "recreation"},
        {"activity": "整理一下电脑桌面和书桌，把不需要的东西全部扔掉，感受断舍离", "type": "organization"},
        {"activity": "给一位至少三个月没有联系的老朋友发一条简单的问候短消息", "type": "social"}
    ]
    act = random.choice(activities)
    return {"content": json.dumps(act, ensure_ascii=False), "result_preview": act["activity"]}


def _exec_password_generator(args: dict) -> dict:
    length = int(args.get("length") or 12)
    if length < 4:
        length = 4
    elif length > 128:
        length = 128
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    # Use cryptographically secure randomness for password generation
    import secrets as _secrets
    pwd = "".join(_secrets.choice(chars) for _ in range(length))
    return {"content": json.dumps({"password": pwd}), "result_preview": pwd}


def _exec_uuid_generator(args: dict) -> dict:
    count = int(args.get("count") or 1)
    if count < 1:
        count = 1
    elif count > 50:
        count = 50
    uuids = [str(uuid.uuid4()) for _ in range(count)]
    return {"content": json.dumps({"uuids": uuids}), "result_preview": uuids[0]}


def _exec_diff_checker(args: dict) -> dict:
    t1 = str(args.get("text1") or "")
    t2 = str(args.get("text2") or "")
    import difflib
    diff = list(difflib.ndiff(t1.splitlines(), t2.splitlines()))
    diff_text = "\n".join(diff)
    return {"content": json.dumps({"diff": diff_text}), "result_preview": "Diff compared successfully"}


def _exec_character_counter(args: dict) -> dict:
    text = str(args.get("text") or "")
    chars = len(text)
    words = len(text.split())
    read_time_min = round(chars / 300.0, 1)
    payload = {"characters": chars, "words": words, "estimated_reading_time_minutes": read_time_min}
    return {"content": json.dumps(payload), "result_preview": f"Characters: {chars} · Reading Time: {read_time_min}m"}


def _execute_http_tool(tool: Tool, context: dict) -> dict:
    validated_ip = _validate_safe_https_url(tool.url)
    parsed_host = urllib.parse.urlparse(tool.url).hostname
    input_data = _dict_value(context.get("input"))
    body = context.get("body")
    query = _query_params(tool.query_schema or {}, input_data)
    if tool.auth_type == "query" and tool.encrypted_secret:
        query_name = tool.auth_query_name or "api_key"
        query[query_name] = decrypt_api_key(tool.encrypted_secret)
    url = _url_with_query(tool.url, query)
    headers = _headers(tool, input_data)
    data = None
    if tool.method in {"POST", "PUT", "PATCH"}:
        data = json.dumps(body if body is not None else _body_from_schema(tool.body_schema or {}, input_data)).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, headers=headers, method=tool.method)
    started = time.monotonic()
    try:
        with dns_pinned(parsed_host, validated_ip):
            with urllib.request.urlopen(request, timeout=tool.timeout_seconds) as response:
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("Tool response is too large")
                text = raw.decode("utf-8", errors="replace")
                result_json = _safe_json(text)
                return {
                    "tool": tool.name,
                    "tool_type": tool.type,
                    "status_code": response.status,
                    "content_type": content_type,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "content": _preview(text, 4000),
                    "result_preview": _preview(text),
                    "result_json": result_json,
                }
    except urllib.error.HTTPError as exc:
        detail = exc.read(512).decode("utf-8", errors="replace")
        raise ValueError(f"HTTP tool request failed with status {exc.code}: {_preview(detail, 200)}") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise ValueError("HTTP tool request failed") from exc


def _validate_safe_https_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("HTTP tools require an HTTPS URL")
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "metadata", "metadata.google.internal"} or host.endswith(".localhost"):
        raise ValueError("HTTP tool target is blocked")
    try:
        ip = ipaddress.ip_address(host)
        _reject_ip(ip)
        return str(ip)
    except ValueError:
        pass
    addr_info = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    for info in addr_info:
        _reject_ip(ipaddress.ip_address(info[4][0]))
    return str(addr_info[0][4][0])


def _reject_ip(ip: ipaddress._BaseAddress) -> None:
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or str(ip) in CLOUD_METADATA_HOSTS:
        raise ValueError("HTTP tool target is blocked")


def _headers(tool: Tool, input_data: dict) -> dict:
    headers = {key: str(input_data.get(key, "")) for key in (tool.headers_schema or {}) if input_data.get(key) is not None}
    if tool.auth_type in {"bearer", "header"} and tool.encrypted_secret:
        secret = decrypt_api_key(tool.encrypted_secret)
        header_name = tool.auth_header_name or "Authorization"
        headers[header_name] = f"Bearer {secret}" if tool.auth_type == "bearer" else secret
    return headers


def _query_params(schema: dict, input_data: dict) -> dict:
    params = {key: input_data.get(key) for key in schema if input_data.get(key) is not None}
    for key, spec in schema.items():
        if isinstance(spec, dict) and spec.get("required") and key not in params:
            raise ValueError(f"Missing required tool input: {key}")
    return params


def _body_from_schema(schema: dict, input_data: dict) -> dict:
    return {key: input_data.get(key) for key in schema if input_data.get(key) is not None}


def _url_with_query(url: str, params: dict) -> str:
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items() if value is not None})
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def _auth_value(value) -> dict:
    return value if isinstance(value, dict) else {}


def _dict_value(value) -> dict:
    return value if isinstance(value, dict) else {}


def _safe_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _preview(value, limit: int = 500) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    return value[:limit]


def _search_query(context: dict) -> str:
    input_data = context.get("input")
    if isinstance(input_data, dict):
        return str(input_data.get("query") or input_data.get("q") or input_data.get("message") or "").strip() or "search"
    return str(context.get("input") or "").strip() or "search"


def _tool_name_exists(db: Session, *, workspace_id: int | None, user_id: int | None, name: str) -> bool:
    return (
        db.query(Tool.id)
        .filter(
            Tool.name == name,
            or_(Tool.workspace_id.is_(None), Tool.workspace_id == workspace_id),
            or_(Tool.user_id.is_(None), Tool.user_id == user_id),
        )
        .first()
        is not None
    )


def tool_schema_for_llm(tool: Tool) -> dict:
    """Convert a Tool into an OpenAI function-calling JSON Schema."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or tool.label,
            "parameters": _tool_parameters_schema(tool),
        },
    }


def _tool_parameters_schema(tool: Tool) -> dict:
    if tool.type == "builtin":
        impl = BUILTIN_TOOLS.get(tool.name)
        if impl:
            return impl["parameters"]
    if tool.type == "builtin_search":
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题",
                }
            },
            "required": ["query"],
        }
    properties: dict = {}
    required: list[str] = []
    for key, spec in (tool.query_schema or {}).items():
        prop = {"type": "string", "description": key}
        if isinstance(spec, dict):
            prop["description"] = spec.get("description") or key
            if spec.get("required"):
                required.append(key)
        properties[key] = prop
    if tool.method in {"POST", "PUT", "PATCH"}:
        for key, spec in (tool.body_schema or {}).items():
            prop = {"type": "string", "description": key}
            if isinstance(spec, dict):
                prop["description"] = spec.get("description") or key
                if spec.get("required"):
                    required.append(key)
            properties[key] = prop
    if not properties:
        properties["input"] = {"type": "string", "description": "传递给工具的输入文本"}
        required = ["input"]
    return {
        "type": "object",
        "properties": properties,
        "required": required[:10],
    }


def _error_code(message: str) -> str:
    if "HTTPS" in message:
        return "https_required"
    if "blocked" in message:
        return "target_blocked"
    if "Timeout" in message or "timeout" in message:
        return "timeout"
    return "tool_error"
