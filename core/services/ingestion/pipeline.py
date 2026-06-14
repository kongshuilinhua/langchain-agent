from __future__ import annotations

import time


class IngestionPipelineError(RuntimeError):
    """某节点失败时抛出，携带失败节点名。"""

    def __init__(self, node: str, original: Exception) -> None:
        super().__init__(f"Ingestion node '{node}' failed: {original}")
        self.node = node
        self.original = original


class IngestionNode:
    """入库管线节点基类：子类设 name 并实现 run(ctx)（就地修改 ctx）。"""

    name: str = "node"

    def run(self, ctx) -> None:
        raise NotImplementedError


class IngestionPipeline:
    """顺序执行节点，逐节点计时+日志；任一节点抛错则记录并以 IngestionPipelineError 中断。"""

    def __init__(self, nodes: list[IngestionNode]) -> None:
        self.nodes = nodes

    def run(self, ctx) -> None:
        for node in self.nodes:
            started = time.monotonic()
            try:
                node.run(ctx)
            except Exception as exc:
                ctx.logs.append({
                    "node": node.name,
                    "status": "failed",
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "message": str(exc)[:300],
                })
                raise IngestionPipelineError(node.name, exc) from exc
            ctx.logs.append({
                "node": node.name,
                "status": "succeeded",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "message": "",
            })
