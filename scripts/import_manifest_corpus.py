from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def request_json(api_base: str, path: str, *, token: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail[:500]}") from exc


def create_knowledge_base(api_base: str, *, token: str, name: str, description: str = "") -> int:
    payload = request_json(api_base, "/api/knowledge-bases", token=token, method="POST", body={"name": name, "description": description})
    return int(payload["knowledge_base"]["id"])


def document_payload(doc: dict, *, max_chars: int | None = None) -> dict:
    text = str(doc.get("text") or "")
    if max_chars and max_chars > 0:
        text = text[:max_chars]
    filename = Path(str(doc.get("relative_path") or doc.get("title") or doc["id"])).name
    return {
        "filename": filename[:255] or f"{doc['id']}.txt",
        "title": str(doc.get("title") or filename or doc["id"])[:255],
        "text": text,
        "content_type": "text/markdown" if str(doc.get("format") or "").lower() in {"md", "markdown"} else "text/plain",
        "source_type": "text",
    }


def import_corpus(
    corpus: list[dict],
    *,
    api_base: str,
    token: str,
    kb_id: int,
    limit: int | None = None,
    source_filter: set[str] | None = None,
    dry_run: bool = False,
    max_chars: int | None = None,
) -> dict:
    imported = 0
    skipped = 0
    for doc in corpus:
        if limit is not None and imported >= limit:
            break
        if source_filter and doc.get("source") not in source_filter:
            skipped += 1
            continue
        payload = document_payload(doc, max_chars=max_chars)
        if not payload["text"].strip():
            skipped += 1
            continue
        if not dry_run:
            request_json(api_base, f"/api/knowledge-bases/{kb_id}/documents", token=token, method="POST", body=payload)
        imported += 1
    return {"imported": imported, "skipped": skipped, "dry_run": dry_run, "kb_id": kb_id}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a normalized JSONL corpus into a knowledge base through the public API.")
    parser.add_argument("--corpus", default="dataset/official_sources/normalized_corpus.jsonl")
    parser.add_argument("--api-base", default=os.getenv("LINGSHU_API_BASE", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.getenv("LINGSHU_TOKEN", ""))
    parser.add_argument("--kb-id", type=int, default=None)
    parser.add_argument("--create-kb", default="")
    parser.add_argument("--description", default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-chars", type=int, default=None)
    args = parser.parse_args(argv)

    if not args.token:
        raise SystemExit("Provide --token or set LINGSHU_TOKEN.")
    if not args.kb_id and not args.create_kb:
        raise SystemExit("Provide --kb-id or --create-kb.")

    kb_id = args.kb_id
    if kb_id is None:
        kb_id = create_knowledge_base(args.api_base, token=args.token, name=args.create_kb, description=args.description)

    corpus = read_jsonl(Path(args.corpus))
    result = import_corpus(
        corpus,
        api_base=args.api_base,
        token=args.token,
        kb_id=kb_id,
        limit=args.limit,
        source_filter=set(args.source) or None,
        dry_run=args.dry_run,
        max_chars=args.max_chars,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
