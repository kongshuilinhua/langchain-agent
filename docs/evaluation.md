# Evaluation

The repo includes a small RAG eval smoke runner for the final local version.

## Case Format

`eval/rag_cases.jsonl` uses JSONL:

```json
{"id":"case-id","question":"问题","expected_sources":["manual.pdf"],"keywords":["故障码"],"should_refuse":false}
```

## Metrics

The mock runner reports:

- `source_hit`
- `top_k_recall`
- `keyword_hit`
- `citation`
- `refuse_correct`

## Command

```powershell
python eval/run_rag_eval.py --cases eval/rag_cases.jsonl --mock
```

Live RAG behavior is covered by API tests. The mock runner is intentionally deterministic and does not require DashScope, Milvus or Redis.
