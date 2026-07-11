from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")


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


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{4,}", "\n\n\n", text).strip()


def title_from_text(text: str, fallback: str) -> str:
    for line in text.splitlines()[:80]:
        match = HEADING_RE.match(line)
        if match:
            return match.group(1).strip()[:180]
    return fallback.replace("_", " ").replace("-", " ").strip()[:180] or "untitled"


def stable_id(*parts: str) -> str:
    raw = "\n".join(part for part in parts if part)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def resolve_inside(root: Path, relative_path: str) -> Path:
    root_resolved = root.resolve()
    path = (root_resolved / relative_path).resolve()
    if root_resolved != path and root_resolved not in path.parents:
        raise ValueError(f"path escapes corpus root: {relative_path}")
    return path


def normalize_manifest(root: Path, manifest: Path, *, source_filter: set[str] | None = None, min_chars: int = 1) -> list[dict]:
    rows: list[dict] = []
    for item in read_jsonl(manifest):
        source = str(item.get("source") or "unknown")
        if source_filter and source not in source_filter:
            continue
        relative_path = str(item.get("relative_path") or item.get("path") or "")
        if not relative_path:
            continue
        page_path = resolve_inside(root, relative_path)
        if not page_path.is_file():
            continue
        text = normalize_text(page_path.read_text(encoding="utf-8", errors="replace"))
        if len(text) < min_chars:
            continue
        url = str(item.get("url") or "")
        title = title_from_text(text, Path(relative_path).stem)
        rows.append(
            {
                "id": str(item.get("id") or stable_id(source, url, relative_path)),
                "source": source,
                "title": title,
                "url": url,
                "relative_path": relative_path,
                "sha256": str(item.get("sha256") or stable_id(text)),
                "format": str(item.get("format") or page_path.suffix.lstrip(".") or "text"),
                "bytes": int(item.get("bytes") or len(text.encode("utf-8"))),
                "text": text,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize manifest-backed document pages into a generic JSONL corpus.")
    parser.add_argument("--root", default="dataset/official_sources", help="corpus root containing manifest rows and page files")
    parser.add_argument("--manifest", default=None, help="manifest JSONL path; defaults to <root>/manifest.jsonl")
    parser.add_argument("--output", default=None, help="output JSONL path; defaults to <root>/normalized_corpus.jsonl")
    parser.add_argument("--source", action="append", default=[], help="optional source filter; can be repeated")
    parser.add_argument("--min-chars", type=int, default=1)
    args = parser.parse_args(argv)

    root = Path(args.root)
    manifest = Path(args.manifest) if args.manifest else root / "manifest.jsonl"
    output = Path(args.output) if args.output else root / "normalized_corpus.jsonl"
    rows = normalize_manifest(root, manifest, source_filter=set(args.source) or None, min_chars=args.min_chars)
    write_jsonl(output, rows)
    print(json.dumps({"output": str(output), "documents": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
