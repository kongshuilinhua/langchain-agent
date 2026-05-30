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
        "description": "获取当前日期和时间，可指定时区。",
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "时区名称，例如 Asia/Shanghai、America/New_York、UTC。留空使用 UTC。",
                }
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
                "expression": {
                    "type": "string",
                    "description": "要计算的数学表达式，例如 '2 + 3 * 4' 或 'sqrt(144)'",
                }
            },
            "required": ["expression"],
        },
        "execute": lambda ctx: _exec_calculator(ctx),
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


def _execute_http_tool(tool: Tool, context: dict) -> dict:
    _validate_safe_https_url(tool.url)
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


def _validate_safe_https_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("HTTP tools require an HTTPS URL")
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "metadata", "metadata.google.internal"} or host.endswith(".localhost"):
        raise ValueError("HTTP tool target is blocked")
    try:
        ip = ipaddress.ip_address(host)
        _reject_ip(ip)
        return
    except ValueError:
        pass
    for info in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM):
        _reject_ip(ipaddress.ip_address(info[4][0]))


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
