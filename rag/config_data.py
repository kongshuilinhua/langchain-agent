from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

md5_path = BASE_DIR / "md5.text"

# Chroma
collection_name = "rag"
persist_directory = BASE_DIR / "chroma_db"

# splitter
chunk_size = 1000
chunk_overlap = 100
separators = ["\n\n", "\n", ".", "!", "?", "。", "！", "？", "，", ""]
max_split_char_number = 1000

similarity_threshold = 2
retrieval_score_threshold = 0.3

embedding_model_name = "text-embedding-v4"
chat_model_name = "qwen3-max"
chat_history_directory = BASE_DIR / "chat_history"


def build_session_config(session_id: str) -> dict:
    return {
        "configurable": {
            "session_id": session_id,
        }
    }
