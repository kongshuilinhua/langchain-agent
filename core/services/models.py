from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import get_settings
from core.db.models import Agent, AgentVersion, ModelConfig


def model_payload(model: ModelConfig) -> dict:
    """
    将 ModelConfig 实体序列化为安全的数据传输字典（DTO）。
    
    🎯 意图与工程大局观：
        隔离数据库实体与前端 API Schema，只向外界透露无害且合法的模型配置属性，避免敏感元数据泄露。
    """
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
    """
    对深度思考（Reasoning）相关字段进行工程规整。

    🎯 意图与工程大局观：
        为多源复杂的推理模型（例如 DeepSeek-R1 具备原生推理，而某些轻量模型需要 Prompt 引导增强推理）提供统一的标准化识别。
        依据 `reasoning_type` 反向推断 `supports_reasoning` 并生成友好的中文展示标签，屏蔽脏数据或不完整前端载荷的影响。
    """
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
    """
    创建模型配置纪录。
    """
    payload = normalize_reasoning_fields(payload)
    model = ModelConfig(**payload)
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


def update_model_config(db: Session, model: ModelConfig, payload: dict) -> ModelConfig:
    """
    更新现有模型配置纪录。
    """
    payload = normalize_reasoning_fields(payload)
    for key, value in payload.items():
        if value is not None:
            setattr(model, key, value)
    db.commit()
    db.refresh(model)
    return model


def delete_model_config(db: Session, model: ModelConfig) -> None:
    """
    删除指定的模型配置记录。

    🛡️ 坚固的防御性安全防线：
        在逻辑/物理删除发生前，依次验证三道金身防护：
        1. 检查是否属于系统预设的“黄金受保护模型名单”（如默认 GPT-4o 或视觉大模型），杜绝系统自毁。
        2. 检查这是否为当前全系统最后唯一可用的“文本问答大模型”，防止误删导致整个智能体广场停摆。
        3. 检查是否有任何现存的“草稿状态智能体”或“已发布的版本快照（Snapshot）”仍在引用该模型。如有，抛出 ValueError，防止后续运行时由于级联外键找不到而发生 Server 500。
    """
    if model.model_name in protected_model_names():
        raise ValueError("Model is protected")
    if deleting_last_enabled_text_model(db, model):
        raise ValueError("Model is protected")
    if model_is_in_use(db, model):
        raise ValueError("Model is in use")

    db.delete(model)
    db.commit()


def protected_model_names() -> set[str]:
    """
    系统黄金核心模型受保护名单。
    """
    settings = get_settings()
    return {settings.openai_model, "qwen-vl-plus"}


def deleting_last_enabled_text_model(db: Session, model: ModelConfig) -> bool:
    """
    🛡️ 防御性设计：判断是否在删除系统中最后唯一可用的文本大模型。
    若 remaining_count == 0，即表示若允许本次删除，系统将彻底失去基本的文本对话服务能力。
    """
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
    """
    判断模型是否被占用。

    ⚡ 性能与边界思考：
        - 检查 `Agent` 表极其高效，利用外键索引快速判断。
        - **重点边界**：除了草稿，必须遍历 `agent_versions` 的 `snapshot` 离线 JSON，检索是否有发布快照绑定了此模型。
    """
    if db.query(Agent.id).filter(Agent.model_id == model.id).first():
        return True
    return any(snapshot_references_model(version.snapshot or {}, model) for version in db.query(AgentVersion).all())


def snapshot_references_model(snapshot: dict, model: ModelConfig) -> bool:
    """
    解析 JSON 版本的 Agent 快照是否与目标模型存在实质绑定。
    支持 ID 与 Model Name（兼容新老版本快照）双向模糊断言。
    """
    if not isinstance(snapshot, dict):
        return False
    snapshot_model_id = snapshot.get("model_id")
    if snapshot_model_id is not None and str(snapshot_model_id) == str(model.id):
        return True
    return snapshot.get("model") == model.model_name


def resolve_agent_model(db: Session, *, model_id: int | None, model_name: str | None) -> ModelConfig | None:
    """
    解析智能体运行时的关联模型配置（最核心决策工厂）。

    🎯 意图与工程大局观：
        为工作流运行时（WorkflowRunner）提供绝对不崩塌的“退化解析策略（Fallback Chain）”。
        
    🛡️ 容错链条：
        1. 优先使用智能体显式绑定的 model_id，若该模型存在且被启用（enabled），完美。
        2. 若 model_id 失效，尝试按 model_name 进行文本模糊匹配，找寻并加载被启用的配置。
        3. 如果均不存在，自动漂移到系统中当前**ID 最小的、处于激活状态的系统默认模型**保底。
        由此机制，哪怕数据库配置发生极剧烈的迁移，Agent 聊天流仍然会被引流到安全的可选备用模型，绝不中断聊天。
    """
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
    """
    规约推理机制类型字符串。
    """
    normalized = str(value or "none").strip()
    if normalized not in {"native", "prompt", "none"}:
        raise ValueError("Invalid model config")
    return normalized


def _reasoning_label(reasoning_type: str) -> str:
    """
    获取推理机制对应的标准中文展示标识。
    """
    return {"native": "深度思考", "prompt": "提示词增强", "none": "不支持"}.get(reasoning_type, "不支持")
