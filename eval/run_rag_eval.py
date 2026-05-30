from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def run_mock_case(case: dict) -> dict:
    question = case.get("question", "")
    expected_sources = case.get("expected_sources", [])
    keywords = case.get("keywords", [])
    should_refuse = bool(case.get("should_refuse"))
    source_hit = 1.0 if expected_sources and not should_refuse else 0.0
    keyword_hit = 1.0 if all(keyword in question or keyword in " ".join(expected_sources) for keyword in keywords) else 0.0
    refuse_correct = 1.0 if should_refuse else 0.0
    citation = 1.0 if expected_sources else 0.0
    return {
        "id": case.get("id"),
        "source_hit": source_hit,
        "top_k_recall": source_hit,
        "keyword_hit": keyword_hit,
        "citation": citation,
        "refuse_correct": refuse_correct,
    }


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {}
    keys = ["source_hit", "top_k_recall", "keyword_hit", "citation", "refuse_correct"]
    return {key: round(sum(row[key] for row in rows) / len(rows), 4) for key in keys}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="eval/rag_cases.jsonl")
    parser.add_argument("--mock", action="store_true")
    args = parser.parse_args()
    cases = load_cases(Path(args.cases))
    if not args.mock:
        raise SystemExit("Only --mock is available in the local eval runner. Use API tests for live RAG validation.")
    rows = [run_mock_case(case) for case in cases]
    print(json.dumps({"summary": summarize(rows), "cases": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
