# LangChain Demo

This project currently includes three main capabilities:

- `main.py`: direct DashScope-compatible LLM call example
- `rag/app_file_upload.py`: knowledge-base management page for uploading and deleting `txt` and `md` files
- `rag/app_qa.py`: RAG chat page with per-session memory and source display

## Environment

The project can load environment variables from a `.env` file at the repo root.

1. Copy `.env.example` to `.env`
2. Fill in your real `DASHSCOPE_API_KEY`

Example:

```env
DASHSCOPE_API_KEY=your_real_key
```

## Install

```bash
pip install -r requirements.txt
```

## Run

Direct model call:

```bash
python main.py
```

Knowledge-base manager:

```bash
streamlit run rag/app_file_upload.py
```

RAG chat:

```bash
streamlit run rag/app_qa.py
```

## Current features

- API key is loaded from environment variables instead of source code
- RAG chat sessions are isolated per browser session
- Knowledge-base paths are relative to the project directory
- The chat page shows matched source snippets and relevance scores
- The system returns a fallback response when retrieval is too weak
- The knowledge-base manager supports listing sources and deleting them by file
