from __future__ import annotations

import re
import time

from sqlalchemy.orm import Session

from core.config import get_settings
from core.db.models import Agent, UserModelConfig
from core.integrations.llm import OpenAICompatibleProvider
from core.security.api_keys import decrypt_api_key, encrypt_api_key


def user_model_payload(config: UserModelConfig) -> dict:
    return {
        "id": config.id,
        "display_name": config.display_name,
        "provider": config.provider,
        "base_url": config.base_url,
        "chat_model": config.chat_model,
        "supports_image": config.supports_image,
        "supports_document": config.supports_document,
        "image_detection": _image_detection_payload(config),
        "supports_reasoning": config.supports_reasoning,
        "reasoning_type": config.reasoning_type,
        "reasoning_label": config.reasoning_label,
        "max_context": config.max_context,
        "default_temperature": config.default_temperature,
        "enabled": config.enabled,
        "is_default": config.is_default,
        "has_api_key": bool(config.encrypted_api_key),
    }


def user_model_snapshot(config: UserModelConfig | None) -> dict | None:
    if not config:
        return None
    return {
        "id": config.id,
        "display_name": config.display_name,
        "provider": config.provider,
        "base_url": config.base_url,
        "chat_model": config.chat_model,
        "supports_image": config.supports_image,
        "supports_document": config.supports_document,
        "image_detection": _image_detection_payload(config),
        "supports_reasoning": config.supports_reasoning,
        "reasoning_type": config.reasoning_type,
        "reasoning_label": config.reasoning_label,
        "max_context": config.max_context,
        "default_temperature": config.default_temperature,
        "enabled": config.enabled,
        "is_default": config.is_default,
    }


def get_owned_user_model(db: Session, *, user_id: int, config_id: int) -> UserModelConfig | None:
    return db.query(UserModelConfig).filter(UserModelConfig.id == config_id, UserModelConfig.user_id == user_id).first()


def list_user_model_configs(db: Session, *, user_id: int) -> list[UserModelConfig]:
    return db.query(UserModelConfig).filter(UserModelConfig.user_id == user_id).order_by(UserModelConfig.id.asc()).all()


def create_user_model_config(db: Session, *, user_id: int, payload: dict) -> UserModelConfig:
    api_key = _required_api_key(payload.get("api_key"))
    data = _config_fields(payload)
    data["supports_image"] = detect_image_support_for_payload(api_key=api_key, data=data)
    if data.get("is_default"):
        _clear_other_defaults(db, user_id=user_id, keep_id=None)
    config = UserModelConfig(
        user_id=user_id,
        encrypted_api_key=encrypt_api_key(api_key),
        **data,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def update_user_model_config(db: Session, *, config: UserModelConfig, payload: dict) -> UserModelConfig:
    should_probe_image = any(key in payload for key in ("api_key", "base_url", "chat_model", "supports_image"))
    if "api_key" in payload:
        api_key = payload["api_key"]
        if api_key is None or not str(api_key).strip():
            raise ValueError("API key cannot be empty")
        config.encrypted_api_key = encrypt_api_key(str(api_key))
    fields = _config_fields(payload, partial=True)
    if fields.get("is_default"):
        _clear_other_defaults(db, user_id=config.user_id, keep_id=config.id)
    if should_probe_image:
        probe_data = _config_data_for_probe(config, fields)
        fields["supports_image"] = detect_image_support_for_payload(
            api_key=decrypt_api_key(config.encrypted_api_key),
            data=probe_data,
        )
    for key, value in fields.items():
        setattr(config, key, value)
    db.commit()
    db.refresh(config)
    return config


def delete_user_model_config(db: Session, *, config: UserModelConfig) -> None:
    if (
        db.query(Agent.id)
        .filter(
            Agent.created_by == config.user_id,
            Agent.user_model_config_id == config.id,
        )
        .first()
    ):
        raise ValueError("Model config is in use")
    db.delete(config)
    db.commit()


def _image_detection_payload(config: UserModelConfig) -> dict:
    return {
        "tested": True,
        "confirmed": bool(config.supports_image),
        "status": "confirmed" if config.supports_image else "failed",
        "source": "backend_probe",
    }


def resolve_user_model_config(
    db: Session,
    *,
    user_id: int,
    config_id: int | None,
    enabled_only: bool = True,
) -> UserModelConfig | None:
    query = db.query(UserModelConfig).filter(UserModelConfig.user_id == user_id)
    if config_id:
        query = query.filter(UserModelConfig.id == config_id)
    else:
        query = query.filter(UserModelConfig.is_default.is_(True))
    if enabled_only:
        query = query.filter(UserModelConfig.enabled.is_(True))
    return query.order_by(UserModelConfig.id.asc()).first()


def user_model_runtime_config(config: UserModelConfig) -> dict:
    return {
        "provider": config.provider,
        "base_url": config.base_url,
        "api_key": decrypt_api_key(config.encrypted_api_key),
        "chat_model": config.chat_model,
        "supports_image": config.supports_image,
        "supports_document": config.supports_document,
        "supports_reasoning": config.supports_reasoning,
        "reasoning_type": config.reasoning_type,
        "reasoning_label": config.reasoning_label,
        "max_context": config.max_context,
        "default_temperature": config.default_temperature,
    }


def test_user_model_config(config: UserModelConfig, *, detect_image: bool = False) -> dict:
    started = time.monotonic()
    checks = {
        "chat": {"ok": False, "required": True},
        "image": {
            "ok": False,
            "required": False,
            "declared": bool(config.supports_image),
            "tested": False,
            "status": "declared" if config.supports_image else "not_tested",
        },
        "reasoning": {
            "ok": bool(config.supports_reasoning and config.reasoning_type != "none"),
            "required": False,
            "type": config.reasoning_type,
        },
    }
    if detect_image:
        checks["image"]["detected"] = True
    try:
        runtime = user_model_runtime_config(config)
        provider = OpenAICompatibleProvider()
        provider.chat(
            [{"role": "user", "content": "connection test"}],
            model=runtime["chat_model"],
            temperature=0,
            runtime_config=runtime,
        )
        checks["chat"]["ok"] = True
        if detect_image:
            image_result = _check_image_capability(provider, runtime, required=False)
            image_ok = image_result["ok"]
            checks["image"]["tested"] = True
            checks["image"]["ok"] = image_ok
            checks["image"]["status"] = "confirmed" if image_ok else "failed"
            if not image_ok:
                checks["image"]["error_code"] = image_result["error_code"]
                checks["image"]["message"] = image_result["message"]
    except Exception as exc:
        checks["chat"]["error_code"] = _chat_probe_error_code(exc)
        checks["chat"]["message"] = _sanitize_probe_error(exc)
        return {
            "ok": False,
            "model": config.chat_model,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "message": _checks_message(checks),
            "error_code": "provider_error",
            "checks": checks,
            "detected_capabilities": _detected_capabilities(checks),
        }
    ok = all(not result.get("required") or result.get("ok") for result in checks.values())
    return {
        "ok": ok,
        "model": config.chat_model,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "message": _checks_message(checks),
        "checks": checks,
        "detected_capabilities": _detected_capabilities(checks),
    }


def test_user_model_payload(payload: dict, *, detect_image: bool = False) -> dict:
    api_key = _required_api_key(payload.get("api_key"))
    data = _config_fields(payload)
    config = UserModelConfig(
        user_id=0,
        encrypted_api_key=encrypt_api_key(api_key),
        **data,
    )
    return test_user_model_config(config, detect_image=detect_image)


def detect_image_support_for_payload(*, api_key: str, data: dict) -> bool:
    config = UserModelConfig(
        user_id=0,
        encrypted_api_key=encrypt_api_key(api_key),
        **{**data, "supports_image": False},
    )
    runtime = user_model_runtime_config(config)
    return _check_image_capability(OpenAICompatibleProvider(), runtime, required=False)["ok"]


def _required_api_key(value) -> str:
    if value is None or not str(value).strip():
        raise ValueError("API key cannot be empty")
    return str(value).strip()


def _config_fields(payload: dict, *, partial: bool = False) -> dict:
    allowed = {
        "display_name",
        "provider",
        "base_url",
        "chat_model",
        "supports_image",
        "supports_document",
        "supports_reasoning",
        "reasoning_type",
        "reasoning_label",
        "max_context",
        "default_temperature",
        "enabled",
        "is_default",
    }
    defaults = {
        "provider": "openai-compatible",
        "supports_image": False,
        "supports_document": True,
        "supports_reasoning": False,
        "reasoning_type": "none",
        "reasoning_label": "不支持",
        "max_context": 131072,
        "default_temperature": 0.4,
        "enabled": True,
        "is_default": False,
    }
    data = {key: payload[key] for key in allowed if key in payload and payload[key] is not None}
    if not partial:
        data = {**defaults, **data}
    for key in ["display_name", "provider", "base_url", "chat_model"]:
        if key in data:
            data[key] = str(data[key]).strip()
    if "reasoning_type" in data:
        data["reasoning_type"] = _reasoning_type(data["reasoning_type"])
        data["supports_reasoning"] = data["reasoning_type"] != "none"
    elif "supports_reasoning" in data:
        data["supports_reasoning"] = bool(data["supports_reasoning"])
        data["reasoning_type"] = "prompt" if data["supports_reasoning"] else "none"
    if "reasoning_label" in data:
        data["reasoning_label"] = str(data["reasoning_label"] or "").strip() or _reasoning_label(data.get("reasoning_type", "none"))
    elif "reasoning_type" in data:
        data["reasoning_label"] = _reasoning_label(data["reasoning_type"])
    required = ["display_name", "base_url", "chat_model"]
    if not partial and any(not data.get(key) for key in required):
        raise ValueError("Invalid model config")
    if any(key in data and not data[key] for key in required):
        raise ValueError("Invalid model config")
    if "provider" in data and data["provider"] != "openai-compatible":
        raise ValueError("Invalid model config")
    return data


def _config_data_for_probe(config: UserModelConfig, fields: dict) -> dict:
    return {
        "display_name": fields.get("display_name", config.display_name),
        "provider": fields.get("provider", config.provider),
        "base_url": fields.get("base_url", config.base_url),
        "chat_model": fields.get("chat_model", config.chat_model),
        "supports_document": fields.get("supports_document", config.supports_document),
        "supports_reasoning": fields.get("supports_reasoning", config.supports_reasoning),
        "reasoning_type": fields.get("reasoning_type", config.reasoning_type),
        "reasoning_label": fields.get("reasoning_label", config.reasoning_label),
        "max_context": fields.get("max_context", config.max_context),
        "default_temperature": fields.get("default_temperature", config.default_temperature),
        "enabled": fields.get("enabled", config.enabled),
        "is_default": fields.get("is_default", config.is_default),
    }


def _reasoning_type(value) -> str:
    normalized = str(value or "none").strip()
    if normalized not in {"native", "prompt", "none"}:
        raise ValueError("Invalid model config")
    return normalized


def _reasoning_label(reasoning_type: str) -> str:
    return {"native": "深度思考", "prompt": "提示词增强", "none": "不支持"}.get(reasoning_type, "不支持")


def _tiny_png_data_url() -> str:
    return (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )


def _check_image_capability(provider: OpenAICompatibleProvider, runtime: dict, *, required: bool) -> dict:
    if get_settings().mock_llm:
        ok = _model_name_implies_image(runtime.get("chat_model", ""))
        return {
            "ok": ok,
            "error_code": "" if ok else "mock_model_name_not_vision",
            "message": "" if ok else "Mock image probe treats this model name as text-only",
        }
    try:
        provider.chat(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe this image briefly"},
                        {"type": "image_url", "image_url": {"url": _tiny_png_data_url()}},
                    ],
                }
            ],
            model=runtime["chat_model"],
            temperature=0,
            runtime_config=runtime,
        )
        return {"ok": True, "error_code": "", "message": ""}
    except Exception as exc:
        if required:
            raise
        return {
            "ok": False,
            "error_code": _image_probe_error_code(exc),
            "message": _sanitize_probe_error(exc),
        }


def _image_probe_error_code(exc: Exception) -> str:
    text = str(exc).lower()
    status = _http_status_from_error(text)
    if status in {401, 403}:
        return "auth_failed"
    if status == 404:
        return "model_not_found"
    if status in {408, 429, 500, 502, 503, 504}:
        return "gateway_unavailable"
    if status == 400 or "invalid" in text or "image_url" in text or "content" in text:
        return "image_payload_rejected"
    if "invalid api key" in text or "unauthorized" in text or "forbidden" in text:
        return "auth_failed"
    if "model" in text and "not" in text:
        return "model_not_found"
    if "cannot connect" in text or "timed out" in text or "timeout" in text:
        return "gateway_unreachable"
    return "image_probe_failed"


def _chat_probe_error_code(exc: Exception) -> str:
    text = str(exc).lower()
    status = _http_status_from_error(text)
    if status in {401, 403}:
        return "auth_failed"
    if status == 404:
        return "model_not_found"
    if status in {408, 429, 500, 502, 503, 504}:
        return "gateway_unavailable"
    if status == 400 or "invalid" in text:
        return "chat_payload_rejected"
    if "invalid api key" in text or "unauthorized" in text or "forbidden" in text:
        return "auth_failed"
    if "model" in text and "not" in text:
        return "model_not_found"
    if "cannot connect" in text or "timed out" in text or "timeout" in text:
        return "gateway_unreachable"
    return "chat_probe_failed"


def _http_status_from_error(text: str) -> int | None:
    match = re.search(r"http\s+(\d{3})", text)
    return int(match.group(1)) if match else None


def _sanitize_probe_error(exc: Exception) -> str:
    message = str(exc)
    message = re.sub(r"(?i)(sk-[A-Za-z0-9_-]+|api[_-]?key\s*[:=]\s*\S+|authorization\s*:\s*\S+|bearer\s+\S+)", "[secret]", message)
    message = re.sub(r"\s+", " ", message).strip()
    return message[:500] or "Image probe failed"


def _model_name_implies_image(model_name: str) -> bool:
    normalized = f"-{str(model_name or '').lower().replace('_', '-')}-"
    markers = (
        "-vl-",
        "-vision-",
        "-visual-",
        "-multimodal-",
        "-omni-",
        "-qvq-",
        "-4v-",
    )
    return any(marker in normalized for marker in markers)


def _detected_capabilities(checks: dict) -> dict:
    reasoning_type = checks.get("reasoning", {}).get("type") or "none"
    supports_reasoning = bool(checks.get("reasoning", {}).get("ok")) and reasoning_type != "none"
    image_check = checks.get("image", {})
    image_confirmed = bool(image_check.get("ok"))
    return {
        "supports_text": bool(checks.get("chat", {}).get("ok")),
        "chat_error_code": checks.get("chat", {}).get("error_code", ""),
        "chat_error": checks.get("chat", {}).get("message", ""),
        "supports_image": image_confirmed,
        "image_confirmed": image_confirmed,
        "image_declared": bool(image_check.get("declared")),
        "image_status": image_check.get("status", "not_tested"),
        "image_error_code": image_check.get("error_code", ""),
        "image_error": image_check.get("message", ""),
        "supports_reasoning": supports_reasoning,
        "reasoning_type": reasoning_type if supports_reasoning else "none",
    }


def _checks_message(checks: dict) -> str:
    failed = [name for name, result in checks.items() if result.get("required") and not result.get("ok")]
    if failed:
        return "Capability check failed: " + ", ".join(failed)
    passed = [name for name, result in checks.items() if result.get("required") and result.get("ok")]
    return "Capability check succeeded: " + ", ".join(passed)


def _clear_other_defaults(db: Session, *, user_id: int, keep_id: int | None) -> None:
    query = db.query(UserModelConfig).filter(UserModelConfig.user_id == user_id, UserModelConfig.is_default.is_(True))
    if keep_id is not None:
        query = query.filter(UserModelConfig.id != keep_id)
    query.update({UserModelConfig.is_default: False}, synchronize_session=False)
