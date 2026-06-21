from types import SimpleNamespace

from core.runtime import self_correct_retrieval as scr
from core.services.rag import RagResult


def test_self_correct_settings_default_disabled(monkeypatch):
    from core.config import Settings

    monkeypatch.delenv("RAG_SELF_CORRECT", raising=False)
    monkeypatch.delenv("RAG_SELF_CORRECT_MAX_ROUNDS", raising=False)
    settings = Settings(_env_file=None)

    assert settings.rag_self_correct is False
    assert settings.rag_self_correct_max_rounds == 2


class _FakeChatModel:
    def __init__(self, grades, rewrites=None):
        self.grades = list(grades)
        self.rewrites = list(rewrites or [])

    def with_structured_output(self, schema, *, method):
        assert method == "function_calling"
        owner = self

        class _Structured:
            def invoke(self, messages):
                if schema is scr.RetrievalGrade:
                    value = owner.grades.pop(0)
                    if isinstance(value, Exception):
                        raise value
                    return schema(sufficient=value)
                return schema(rewritten_query=owner.rewrites.pop(0))

        return _Structured()


def _fake_retrieve(queries):
    def retrieve(db, *, workspace_id, knowledge_base_ids, query, config, runtime_config=None):
        queries.append(query)
        return RagResult(
            sources=[{"title": "doc", "content": f"source for {query}"}],
            status={"query": query, "reason": "available"},
        )

    return retrieve


def test_self_correct_rewrites_then_returns_second_round(monkeypatch):
    queries = []
    fake_chat = _FakeChatModel([False, True], ["改写后的检索问题"])
    monkeypatch.setattr(scr.rag, "retrieve", _fake_retrieve(queries))
    monkeypatch.setattr(scr, "get_chat_model", lambda **kwargs: fake_chat)

    result = scr.self_correct_retrieve(
        object(),
        workspace_id=7,
        knowledge_base_ids=[11],
        query="原问题",
        config={"self_correct_max_rounds": 2},
    )

    assert queries == ["原问题", "改写后的检索问题"]
    assert result.sources == [{"title": "doc", "content": "source for 改写后的检索问题"}]
    assert result.status["self_correct"]["rounds"] == 2
    assert result.status["self_correct"]["rewritten"] is True


def test_self_correct_stops_at_max_rounds(monkeypatch):
    queries = []
    fake_chat = _FakeChatModel([False, False], ["第二轮问题"])
    monkeypatch.setattr(scr.rag, "retrieve", _fake_retrieve(queries))
    monkeypatch.setattr(scr, "get_chat_model", lambda **kwargs: fake_chat)

    result = scr.self_correct_retrieve(
        object(),
        workspace_id=7,
        knowledge_base_ids=[11],
        query="第一轮问题",
        config={"self_correct_max_rounds": 2},
    )

    assert queries == ["第一轮问题", "第二轮问题"]
    assert result.status["self_correct"]["rounds"] == 2
    assert result.status["self_correct"]["final_query"] == "第二轮问题"


def test_grade_error_accepts_single_round(monkeypatch):
    queries = []
    fake_chat = _FakeChatModel([RuntimeError("grader down")])
    monkeypatch.setattr(scr.rag, "retrieve", _fake_retrieve(queries))
    monkeypatch.setattr(scr, "get_chat_model", lambda **kwargs: fake_chat)

    result = scr.self_correct_retrieve(
        object(),
        workspace_id=7,
        knowledge_base_ids=[11],
        query="无需改写",
        config={"self_correct_max_rounds": 2},
    )

    assert queries == ["无需改写"]
    assert result.status["self_correct"]["rounds"] == 1
    assert result.status["self_correct"]["grade_error"] is True


def test_internal_error_falls_back_to_native_retrieve(monkeypatch):
    expected = RagResult([{"content": "native"}], {"reason": "available"})
    calls = []

    def native_retrieve(db, **kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(scr, "_build_graph", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("graph down")))
    monkeypatch.setattr(scr.rag, "retrieve", native_retrieve)

    result = scr.self_correct_retrieve(
        object(),
        workspace_id=7,
        knowledge_base_ids=[11],
        query="原查询",
        config={"self_correct_max_rounds": 2},
        runtime_config={"chat_model": "x"},
    )

    assert result is expected
    assert len(calls) == 1
    assert calls[0]["query"] == "原查询"


def test_workflow_flag_off_uses_native_retrieve(monkeypatch):
    from core.runtime import workflow

    expected = RagResult([{"content": "native"}], {"reason": "available"})
    calls = []

    def native_retrieve(db, **kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(workflow, "get_settings", lambda: SimpleNamespace(rag_self_correct=False))
    monkeypatch.setattr(workflow, "retrieve", native_retrieve)
    monkeypatch.setattr(
        scr,
        "self_correct_retrieve",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("self-correct must stay off")),
    )
    runner = workflow.WorkflowRunner.__new__(workflow.WorkflowRunner)
    runner.db = object()
    agent = SimpleNamespace(
        workspace_id=7,
        knowledge_base_ids=[11],
        runtime_config=None,
    )

    output = runner._execute_node(
        agent,
        {"type": "Knowledge", "config": {"top_k": 4}},
        {"input": "原生问题", "rag_enabled": True, "rag_config": {}},
    )

    assert len(calls) == 1
    assert calls[0]["query"] == "原生问题"
    assert output["sources"] == expected.sources


def test_workflow_flag_on_uses_self_correct_retrieve(monkeypatch):
    from core.runtime import workflow

    expected = RagResult([{"content": "corrected"}], {"self_correct": {"rounds": 1}})
    calls = []

    def corrected_retrieve(db, **kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(workflow, "get_settings", lambda: SimpleNamespace(rag_self_correct=True))
    monkeypatch.setattr(
        workflow,
        "retrieve",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("native retrieve must stay unused")),
    )
    monkeypatch.setattr(scr, "self_correct_retrieve", corrected_retrieve)
    runner = workflow.WorkflowRunner.__new__(workflow.WorkflowRunner)
    runner.db = object()
    agent = SimpleNamespace(workspace_id=7, knowledge_base_ids=[11], runtime_config=None)

    output = runner._execute_node(
        agent,
        {"type": "Knowledge", "config": {"top_k": 4}},
        {"input": "自纠问题", "rag_enabled": True, "rag_config": {}},
    )

    assert len(calls) == 1
    assert calls[0]["query"] == "自纠问题"
    assert output["sources"] == expected.sources
