from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import get_settings
from core.db.models import Agent, AgentVersion, ModelConfig


def model_payload(model: ModelConfig) -> dict:
    return {
        "id": model.id,
        "provider": model.provider,
        "model_name": model.model_name,
        "display_name": model.display_name,
        "supports_text": model.supports_text,
        "supports_image": model.supports_image,
        "supports_document": model.supports_document,
        "supports_reasoning": model.supports_reasoning,
        "reasoning_type": model.reasoning_type,
        "reasoning_label": model.reasoning_label,
        "max_context": model.max_context,
        "default_temperature": model.default_temperature,
        "enabled": model.enabled,
    }


def normalize_reasoning_fields(payload: dict) -> dict:
    data = dict(payload)
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
    return data


def create_model_config(db: Session, payload: dict) -> ModelConfig:
    payload = normalize_reasoning_fields(payload)
    model = ModelConfig(**payload)
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


def update_model_config(db: Session, model: ModelConfig, payload: dict) -> ModelConfig:
    payload = normalize_reasoning_fields(payload)
    for key, value in payload.items():
        if value is not None:
            setattr(model, key, value)
    db.commit()
    db.refresh(model)
    return model


def delete_model_config(db: Session, model: ModelConfig) -> None:
    if model.model_name in protected_model_names():
        raise ValueError("Model is protected")
    if deleting_last_enabled_text_model(db, model):
        raise ValueError("Model is protected")
    if model_is_in_use(db, model):
        raise ValueError("Model is in use")

    db.delete(model)
    db.commit()


def protected_model_names() -> set[str]:
    settings = get_settings()
    return {settings.openai_model, "qwen-vl-plus"}


def deleting_last_enabled_text_model(db: Session, model: ModelConfig) -> bool:
    if not (model.enabled and model.supports_text):
        return False
    remaining_count = (
        db.query(ModelConfig)
        .filter(
            ModelConfig.id != model.id,
            ModelConfig.enabled.is_(True),
            ModelConfig.supports_text.is_(True),
        )
        .count()
    )
    return remaining_count == 0


def model_is_in_use(db: Session, model: ModelConfig) -> bool:
    if db.query(Agent.id).filter(Agent.model_id == model.id).first():
        return True
    return any(snapshot_references_model(version.snapshot or {}, model) for version in db.query(AgentVersion).all())


def snapshot_references_model(snapshot: dict, model: ModelConfig) -> bool:
    if not isinstance(snapshot, dict):
        return False
    snapshot_model_id = snapshot.get("model_id")
    if snapshot_model_id is not None and str(snapshot_model_id) == str(model.id):
        return True
    return snapshot.get("model") == model.model_name


def resolve_agent_model(db: Session, *, model_id: int | None, model_name: str | None) -> ModelConfig | None:
    if model_id:
        model = db.get(ModelConfig, model_id)
        if model and model.enabled:
            return model
    if model_name:
        model = db.query(ModelConfig).filter(ModelConfig.model_name == model_name, ModelConfig.enabled.is_(True)).first()
        if model:
            return model
    return db.query(ModelConfig).filter(ModelConfig.enabled.is_(True)).order_by(ModelConfig.id.asc()).first()


def _reasoning_type(value) -> str:
    normalized = str(value or "none").strip()
    if normalized not in {"native", "prompt", "none"}:
        raise ValueError("Invalid model config")
    return normalized


def _reasoning_label(reasoning_type: str) -> str:
    return {"native": "深度思考", "prompt": "提示词增强", "none": "不支持"}.get(reasoning_type, "不支持")
