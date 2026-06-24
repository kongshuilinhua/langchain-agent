from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IngestionContext:
    """贯穿入库管线的上下文（就地被各节点修改）。"""

    workspace_id: int
    knowledge_base_id: int
    document_id: int
    filename: str
    content_type: str
    text: str
    title: str = ""
    segment_config: dict = field(default_factory=dict)
    runtime_config: dict | None = None
    children: list[dict] = field(default_factory=list)
    parents: list[dict] = field(default_factory=list)
    embeddings: list[list[float]] = field(default_factory=list)
    logs: list[dict] = field(default_factory=list)
