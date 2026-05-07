import hashlib
import json
from datetime import datetime
from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config_data as config


def _ensure_registry_file() -> None:
    registry_path = Path(config.md5_path)
    if not registry_path.exists():
        registry_path.write_text("[]", encoding="utf-8")


def _load_registry() -> list[dict]:
    _ensure_registry_file()
    registry_path = Path(config.md5_path)
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = []
    return data if isinstance(data, list) else []


def _save_registry(records: list[dict]) -> None:
    Path(config.md5_path).write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_string_md5(input_str: str, encoding: str = "utf-8") -> str:
    md5_obj = hashlib.md5()
    md5_obj.update(input_str.encode(encoding))
    return md5_obj.hexdigest()


class KnowledgeBaseService:
    def __init__(self):
        Path(config.persist_directory).mkdir(parents=True, exist_ok=True)
        self.chroma = Chroma(
            collection_name=config.collection_name,
            embedding_function=DashScopeEmbeddings(model=config.embedding_model_name),
            persist_directory=config.persist_directory,
        )
        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            separators=config.separators,
            length_function=len,
        )

    def upload_by_str(self, data: str, file_name: str) -> str:
        md5_hex = get_string_md5(data)
        registry = _load_registry()
        for record in registry:
            if record["source"] == file_name and record["md5"] == md5_hex:
                return "[跳过] 相同文件内容已经存在于知识库中"

        knowledge_chunks = (
            self.spliter.split_text(data)
            if len(data) > config.max_split_char_number
            else [data]
        )

        metadata = {
            "source": file_name,
            "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "operator": "local_user",
            "content_md5": md5_hex,
        }

        self.chroma.add_texts(
            knowledge_chunks,
            metadatas=[metadata.copy() for _ in knowledge_chunks],
        )
        registry.append(
            {
                "source": file_name,
                "md5": md5_hex,
                "create_time": metadata["create_time"],
            }
        )
        _save_registry(registry)
        return f"[成功] 已写入知识库，共 {len(knowledge_chunks)} 个文本分块"

    def list_sources(self) -> list[dict]:
        registry = _load_registry()
        latest_by_source: dict[str, dict] = {}
        for record in registry:
            latest_by_source[record["source"]] = record

        sources = []
        for source, record in latest_by_source.items():
            result = self.chroma.get(
                where={"source": source},
                include=["metadatas"],
            )
            chunk_count = len(result.get("ids", []))
            sources.append(
                {
                    "source": source,
                    "create_time": record.get("create_time", "unknown"),
                    "chunk_count": chunk_count,
                }
            )

        return sorted(sources, key=lambda item: item["create_time"], reverse=True)

    def delete_by_source(self, source: str) -> str:
        result = self.chroma.get(where={"source": source})
        ids = result.get("ids", [])
        if not ids:
            return f"[跳过] 知识库中不存在来源 {source}"

        self.chroma.delete(ids=ids)
        registry = [record for record in _load_registry() if record["source"] != source]
        _save_registry(registry)
        return f"[成功] 已删除来源 {source}，共移除 {len(ids)} 个文本分块"
