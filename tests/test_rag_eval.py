from eval.run_rag_eval import load_cases, run_mock_case, summarize


def test_mock_rag_eval_cases_load_and_summarize():
    cases = load_cases(__import__("pathlib").Path("eval/rag_cases.jsonl"))
    rows = [run_mock_case(case) for case in cases]
    summary = summarize(rows)

    assert cases
    assert "source_hit" in summary
    assert "refuse_correct" in summary
