import json
from pathlib import Path

from eval.run_rag_eval import run_offline_case, summarize
from scripts.build_rag_eval_cases import build_cases
from scripts.import_manifest_corpus import document_payload
from scripts.normalize_manifest_corpus import normalize_manifest


def test_normalize_manifest_corpus_reads_pages(tmp_path: Path):
    root = tmp_path / "corpus"
    page = root / "fixture" / "pages" / "intro.md"
    page.parent.mkdir(parents=True)
    page.write_text("# Intro Title\n\nalpha-token content", encoding="utf-8")
    manifest = root / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "source": "fixture",
                "url": "https://example.test/intro",
                "relative_path": "fixture/pages/intro.md",
                "sha256": "abc",
                "format": "markdown",
                "bytes": page.stat().st_size,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rows = normalize_manifest(root, manifest)

    assert len(rows) == 1
    assert rows[0]["title"] == "Intro Title"
    assert rows[0]["source"] == "fixture"
    assert rows[0]["text"].startswith("# Intro Title")


def test_build_rag_eval_cases_from_normalized_corpus():
    corpus = [
        {
            "id": "doc-a",
            "source": "fixture",
            "title": "Alpha Guide",
            "url": "https://example.test/alpha",
            "text": "alpha-token explains beta-token configuration. alpha-token matters.",
        }
    ]

    cases = build_cases(corpus, limit=1, negative_count=1, id_prefix="fixture", keywords_per_case=3, min_chars=1)

    assert len(cases) == 2
    assert cases[0]["expected_source_ids"] == ["doc-a"]
    assert cases[0]["should_refuse"] is False
    assert cases[1]["should_refuse"] is True


def test_run_rag_eval_offline_scores_expected_source():
    corpus = [
        {"id": "doc-a", "title": "Alpha Guide", "url": "https://example.test/alpha", "text": "alpha-token explains beta-token configuration."},
        {"id": "doc-b", "title": "Other Guide", "url": "https://example.test/other", "text": "unrelated material"},
    ]
    case = {
        "id": "alpha",
        "question": "Explain alpha-token.",
        "expected_source_ids": ["doc-a"],
        "keywords": ["alpha-token"],
        "should_refuse": False,
    }

    row = run_offline_case(case, corpus, top_k=1)
    summary = summarize([row])

    assert row["retrieved_ids"] == ["doc-a"]
    assert summary["source_hit"] == 1.0
    assert summary["keyword_hit"] == 1.0


def test_import_manifest_corpus_document_payload():
    payload = document_payload(
        {
            "id": "doc-a",
            "title": "Alpha Guide",
            "relative_path": "fixture/pages/intro.md",
            "format": "markdown",
            "text": "alpha-token content",
        }
    )

    assert payload["filename"] == "intro.md"
    assert payload["title"] == "Alpha Guide"
    assert payload["content_type"] == "text/markdown"
    assert payload["source_type"] == "text"
