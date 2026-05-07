# langchain-agent

This repository contains a Streamlit-based LangChain agent project and a lightweight local RAG demo workflow.

## Main entry points

- `app.py`: original Streamlit agent application
- `main.py`: direct DashScope-compatible LLM call example
- `rag/app_qa.py`: lightweight RAG chat page with per-session memory, source display, and fallback on weak retrieval
- `rag/app_file_upload.py`: knowledge-base manager for uploading, listing, and deleting `txt` and `md` files

## Environment

Copy `.env.example` to `.env` and fill in your real credentials:

```env
DASHSCOPE_API_KEY=your_real_key
AGENT_USER_CITY=Shanghai
AGENT_USER_ID=1001
```

`AGENT_USER_CITY` and `AGENT_USER_ID` are optional and are mainly used by the original agent workflow.

## Install

```bash
pip install -r requirements.txt
```

## Run

Original agent app:

```bash
streamlit run app.py
```

RAG knowledge-base manager:

```bash
streamlit run rag/app_file_upload.py
```

RAG chat demo:

```bash
streamlit run rag/app_qa.py
```

Direct model call demo:

```bash
python main.py
```

## Current improvements

- API keys are loaded from environment variables instead of hardcoded source values
- RAG chat sessions are isolated per browser session
- Knowledge-base paths are relative to the project directory
- The RAG page shows matched source snippets and relevance scores
- The system returns a fallback response when retrieval is too weak
- The knowledge-base manager supports listing sources and deleting them by file

## Notes

- Local vector-store data, chat history, and `.env` are ignored by Git
- The RAG management page currently supports `txt` and `md` sources
