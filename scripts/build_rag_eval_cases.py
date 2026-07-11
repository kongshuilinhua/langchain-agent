from __future__ import annotations

import argparse
import json
import re
from collections import Counter
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


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def text_tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def document_frequencies(corpus: list[dict]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for doc in corpus:
        tokens = {token for token in text_tokens(f"{doc.get('title', '')}\n{doc.get('text', '')}") if token not in STOPWORDS and len(token) >= 3}
        counts.update(tokens)
    return counts


def extract_keywords(text: str, *, limit: int = 5, frequencies: Counter[str] | None = None, document_count: int = 0) -> list[str]:
    counts: Counter[str] = Counter()
    for normalized in text_tokens(text):
        if len(normalized) < 3 or normalized in STOPWORDS:
            continue
        counts[normalized] += 1
    max_df = max(3, int(document_count * 0.08)) if document_count else None
    scored = []
    for token, count in counts.items():
        df = frequencies.get(token, 1) if frequencies else 1
        if max_df and df > max_df:
            continue
        scored.append((count / df, count, token))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [token for _, _, token in scored[:limit]]


def build_positive_case(doc: dict, index: int, *, id_prefix: str, keywords_per_case: int, frequencies: Counter[str], document_count: int) -> dict | None:
    text = str(doc.get("text") or "")
    keywords = extract_keywords(f"{doc.get('title', '')}\n{text}", limit=keywords_per_case, frequencies=frequencies, document_count=document_count)
    if not keywords:
        return None
    anchor = keywords[0]
    title = str(doc.get("title") or "document")
    return {
        "id": f"{id_prefix}-doc-{index:04d}",
        "intent": "knowledge",
        "question": f"Explain {title} with focus on {anchor}.",
        "expected_source_ids": [doc["id"]],
        "expected_sources": [doc.get("url") or doc.get("relative_path") or title],
        "keywords": keywords,
        "answer_keywords": keywords[: min(3, len(keywords))],
        "should_refuse": False,
    }


def build_cases(
    corpus: list[dict],
    *,
    limit: int,
    negative_count: int,
    id_prefix: str,
    keywords_per_case: int,
    source_filter: set[str] | None = None,
    min_chars: int = 120,
) -> list[dict]:
    cases: list[dict] = []
    eligible_docs = [
        doc
        for doc in corpus
        if (not source_filter or doc.get("source") in source_filter) and len(str(doc.get("text") or "")) >= min_chars
    ]
    frequencies = document_frequencies(eligible_docs)
    document_count = len(eligible_docs)
    for doc in eligible_docs:
        if len(cases) >= limit:
            break
        case = build_positive_case(
            doc,
            len(cases) + 1,
            id_prefix=id_prefix,
            keywords_per_case=keywords_per_case,
            frequencies=frequencies,
            document_count=document_count,
        )
        if case:
            cases.append(case)

    for index in range(negative_count):
        cases.append(
            {
                "id": f"{id_prefix}-no-evidence-{index + 1:02d}",
                "intent": "knowledge",
                "question": f"zzzz_absent_eval_token_{index + 1:02d}",
                "expected_source_ids": [],
                "expected_sources": [],
                "keywords": [],
                "answer_keywords": [],
                "should_refuse": True,
            }
        )
    return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build deterministic RAG eval cases from a normalized JSONL corpus.")
    parser.add_argument("--corpus", default="dataset/official_sources/normalized_corpus.jsonl")
    parser.add_argument("--output", default="dataset/official_sources/generated_rag_cases.jsonl")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--negative-count", type=int, default=5)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--id-prefix", default="local-corpus")
    parser.add_argument("--keywords-per-case", type=int, default=5)
    parser.add_argument("--min-chars", type=int, default=120)
    args = parser.parse_args(argv)

    corpus = read_jsonl(Path(args.corpus))
    cases = build_cases(
        corpus,
        limit=args.limit,
        negative_count=args.negative_count,
        id_prefix=args.id_prefix,
        keywords_per_case=args.keywords_per_case,
        source_filter=set(args.source) or None,
        min_chars=args.min_chars,
    )
    write_jsonl(Path(args.output), cases)
    print(json.dumps({"output": args.output, "cases": len(cases)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
