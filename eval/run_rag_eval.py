from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_/-]{2,}")
STOPWORDS = {
    "about",
    "after",
    "and",
    "api",
    "are",
    "body",
    "can",
    "content",
    "data",
    "description",
    "documentation",
    "error",
    "example",
    "explain",
    "focus",
    "for",
    "from",
    "get",
    "how",
    "http",
    "https",
    "into",
    "json",
    "message",
    "object",
    "openapi",
    "parameters",
    "post",
    "properties",
    "request",
    "required",
    "response",
    "schema",
    "string",
    "that",
    "the",
    "this",
    "title",
    "type",
    "use",
    "using",
    "validation",
    "with",
    "you",
    "your",
}
METRIC_KEYS = [
    "source_hit",
    "top_k_recall",
    "mrr",
    "keyword_hit",
    "citation",
    "refuse_correct",
    "no_evidence_correct",
    "forbidden_keyword_hit",
]


def load_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def load_corpus(path: Path) -> list[dict]:
    corpus = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            corpus.append(json.loads(line))
    return corpus


def run_mock_case(case: dict) -> dict:
    question = case.get("question", "")
    expected_sources = case.get("expected_sources", [])
    keywords = case.get("keywords", [])
    should_refuse = bool(case.get("should_refuse"))
    source_hit = 1.0 if expected_sources and not should_refuse else None
    keyword_hit = 1.0 if keywords and all(keyword in question or keyword in " ".join(expected_sources) for keyword in keywords) else None
    refuse_correct = 1.0 if should_refuse else None
    citation = 1.0 if expected_sources else None
    return {
        "id": case.get("id"),
        "source_hit": source_hit,
        "top_k_recall": source_hit,
        "mrr": source_hit,
        "keyword_hit": keyword_hit,
        "citation": citation,
        "refuse_correct": refuse_correct,
        "no_evidence_correct": refuse_correct,
        "forbidden_keyword_hit": 0.0,
    }


def summarize(rows: list[dict]) -> dict:
    if not rows:
        return {}
    summary = {}
    for key in METRIC_KEYS:
        values = [float(row[key]) for row in rows if isinstance(row.get(key), int | float)]
        if values:
            summary[key] = round(sum(values) / len(values), 4)
    return summary


def tokenize(value: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(value or "")]


def meaningful_tokens(value: str) -> list[str]:
    return [token for token in tokenize(value) if token not in STOPWORDS and len(token) >= 3]


def expected_ids(case: dict) -> set[str]:
    ids = case.get("expected_source_ids")
    if ids:
        return {str(item) for item in ids}
    return {str(item) for item in case.get("expected_sources", [])}


def doc_identity_values(doc: dict) -> set[str]:
    return {
        str(doc.get("id") or ""),
        str(doc.get("url") or ""),
        str(doc.get("relative_path") or ""),
        str(doc.get("title") or ""),
    }


def matches_expected(doc: dict, expected: set[str]) -> bool:
    if not expected:
        return False
    values = doc_identity_values(doc)
    return any(item in values for item in expected)


def score_document(case: dict, doc: dict) -> float:
    question = str(case.get("question") or "")
    keywords = [str(item).lower() for item in case.get("keywords", [])]
    title = str(doc.get("title") or "")
    text = str(doc.get("text") or "")
    haystack = f"{title}\n{text}".lower()

    score = 0.0
    query_tokens = set(meaningful_tokens(question))
    doc_tokens = set(meaningful_tokens(f"{title}\n{text[:20000]}"))
    score += len(query_tokens & doc_tokens)
    for keyword in keywords:
        if keyword and keyword in haystack:
            score += 8.0
    title_tokens = set(tokenize(title))
    score += 2.0 * len(query_tokens & title_tokens)
    return score


def retrieve(case: dict, corpus: list[dict], *, top_k: int) -> list[dict]:
    scored = [(score_document(case, doc), doc) for doc in corpus]
    scored = [(score, doc) for score, doc in scored if score > 0]
    scored.sort(key=lambda item: (-item[0], str(item[1].get("id") or "")))
    return [doc | {"_eval_score": round(score, 4)} for score, doc in scored[:top_k]]


def context_for_hits(hits: list[dict]) -> str:
    return "\n".join(str(hit.get("text") or "") for hit in hits).lower()


def run_offline_case(case: dict, corpus: list[dict], *, top_k: int = 5) -> dict:
    hits = retrieve(case, corpus, top_k=top_k)
    expected = expected_ids(case)
    should_refuse = bool(case.get("should_refuse"))
    hit_ids = [str(hit.get("id") or "") for hit in hits]
    matched_positions = [index + 1 for index, hit in enumerate(hits) if matches_expected(hit, expected)]
    matched_count = len(matched_positions)
    context = context_for_hits(hits)
    keywords = [str(item).lower() for item in case.get("keywords", [])]
    forbidden = [str(item).lower() for item in case.get("forbidden_keywords", [])]

    if expected:
        source_hit = 1.0 if matched_count else 0.0
        recall = matched_count / len(expected)
        mrr = 1.0 / matched_positions[0] if matched_positions else 0.0
    else:
        source_hit = 0.0
        recall = 0.0
        mrr = 0.0

    keyword_hit = 1.0 if not keywords or all(keyword in context for keyword in keywords) else 0.0
    forbidden_hit = 1.0 if any(keyword and keyword in context for keyword in forbidden) else 0.0
    no_evidence_correct = 1.0 if should_refuse and not hits else 0.0 if should_refuse else None
    refuse_correct = no_evidence_correct if should_refuse else None

    return {
        "id": case.get("id"),
        "source_hit": source_hit if expected else None,
        "top_k_recall": round(recall, 4) if expected else None,
        "mrr": round(mrr, 4) if expected else None,
        "keyword_hit": keyword_hit if keywords else None,
        "citation": 1.0 if hits and not should_refuse and expected else None,
        "refuse_correct": refuse_correct,
        "no_evidence_correct": no_evidence_correct,
        "forbidden_keyword_hit": forbidden_hit,
        "retrieved_ids": hit_ids,
        "retrieved": [
            {
                "id": hit.get("id"),
                "title": hit.get("title"),
                "url": hit.get("url"),
                "score": hit.get("_eval_score"),
            }
            for hit in hits
        ],
    }


def check_thresholds(summary: dict, thresholds: dict[str, float | None]) -> list[str]:
    failures = []
    for key, minimum in thresholds.items():
        if minimum is None:
            continue
        actual = float(summary.get(key, 0.0))
        if actual < minimum:
            failures.append(f"{key} {actual:.4f} < {minimum:.4f}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="eval/rag_cases.jsonl")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--corpus", default="", help="normalized JSONL corpus for deterministic offline retrieval evaluation")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-source-hit", type=float, default=None)
    parser.add_argument("--min-top-k-recall", type=float, default=None)
    parser.add_argument("--min-keyword-hit", type=float, default=None)
    parser.add_argument("--min-refuse-correct", type=float, default=None)
    parser.add_argument("--summary-only", action="store_true", help="print only aggregate metrics")
    args = parser.parse_args()
    cases = load_cases(Path(args.cases))
    if args.mock:
        rows = [run_mock_case(case) for case in cases]
    elif args.corpus:
        corpus = load_corpus(Path(args.corpus))
        rows = [run_offline_case(case, corpus, top_k=args.top_k) for case in cases]
    else:
        raise SystemExit("Use --mock for schema checks or --corpus <normalized_corpus.jsonl> for offline retrieval evaluation.")
    summary = summarize(rows)
    payload = {"summary": summary} if args.summary_only else {"summary": summary, "cases": rows}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    failures = check_thresholds(
        summary,
        {
            "source_hit": args.min_source_hit,
            "top_k_recall": args.min_top_k_recall,
            "keyword_hit": args.min_keyword_hit,
            "refuse_correct": args.min_refuse_correct,
        },
    )
    if failures:
        raise SystemExit("RAG eval thresholds failed: " + "; ".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
