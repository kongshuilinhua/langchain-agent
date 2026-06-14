from eval.run_rag_eval import load_cases, run_mock_case, summarize


def test_mock_rag_eval_cases_load_and_summarize():
    cases = load_cases(__import__("pathlib").Path("eval/rag_cases.jsonl"))
    rows = [run_mock_case(case) for case in cases]
    summary = summarize(rows)

    assert cases
    assert "source_hit" in summary
    assert "refuse_correct" in summary


def test_eval_has_intent_cases():
    import json
    from pathlib import Path

    cases = [
        json.loads(line)
        for line in Path("eval/rag_cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    intents = {case.get("intent") for case in cases if "intent" in case}
    assert {"chitchat", "knowledge"}.issubset(intents)
