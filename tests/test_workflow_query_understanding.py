from types import SimpleNamespace

from core.runtime import workflow
from core.runtime.workflow import WorkflowRunner


def test_query_understanding_skips_model_when_rag_has_no_knowledge_base(monkeypatch):
    runner = WorkflowRunner(db=None)
    runtime = SimpleNamespace(settings={"query_understanding": {}}, runtime_config=None)
    context = {
        "input": "2+2",
        "rag_enabled": True,
        "knowledge_base_ids": [],
        "memory_summary": "",
    }

    def fail_if_called(*args, **kwargs):
        raise AssertionError("query understanding model should not run without knowledge bases")

    monkeypatch.setattr(workflow.qu_service, "analyze", fail_if_called)

    runner._understand_query(runtime, context)

    assert context["rewritten_query"] == "2+2"
    assert context["query_understanding_event"]["applied"] is False
    assert context["query_understanding_event"]["reason"] == "no_knowledge_base"
