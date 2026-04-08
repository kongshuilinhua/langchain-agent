from langchain_chroma import Chroma
from chromadb.config import Settings
from utils.config_handler import chroma_conf
from model.factory import get_embedding_model
from langchain_text_splitters import RecursiveCharacterTextSplitter
from utils.path_tool import get_abs_path
import hashlib
import json
import os
import shutil
from datetime import datetime
from utils.file_handler import (
    clean_text,
    get_file_md5_hex,
    listdir_with_allowed_type,
    normalize_documents,
    pdf_loader,
    split_qa_documents,
    txt_loader,
)
from utils.logger_handler import logger


class VectorStoreService:
    def __init__(self):
        self.collection_name = chroma_conf['collection_name']
        self.persist_directory = get_abs_path(chroma_conf['persist_directory'])
        self.md5_hex_store = get_abs_path(chroma_conf['md5_hex_store'])
        self.manifest_store = get_abs_path(
            chroma_conf.get('manifest_store', os.path.join(self.persist_directory, 'knowledge_manifest.json'))
        )
        os.makedirs(self.persist_directory, exist_ok=True)
        manifest_dir = os.path.dirname(self.manifest_store)
        if manifest_dir:
            os.makedirs(manifest_dir, exist_ok=True)
        # 关闭 Chroma 匿名遥测，避免无关 telemetry 报错干扰。
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
        self.vector_store = self._create_vector_store()
        self.default_splitter = self._build_splitter(
            chunk_size=chroma_conf['chunk_size'],
            chunk_overlap=chroma_conf['chunk_overlap'],
        )
        self.txt_splitter = self._build_splitter(
            chunk_size=chroma_conf.get('txt_chunk_size', chroma_conf['chunk_size']),
            chunk_overlap=chroma_conf.get('txt_chunk_overlap', chroma_conf['chunk_overlap']),
        )
        self.pdf_splitter = self._build_splitter(
            chunk_size=chroma_conf.get('pdf_chunk_size', chroma_conf['chunk_size']),
            chunk_overlap=chroma_conf.get('pdf_chunk_overlap', chroma_conf['chunk_overlap']),
        )

    def _build_splitter(self, chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
        return RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=chroma_conf['separators'],
            length_function=len,
        )

    def _get_splitter(self, read_path: str) -> RecursiveCharacterTextSplitter:
        if read_path.endswith(".txt"):
            return self.txt_splitter
        if read_path.endswith(".pdf"):
            return self.pdf_splitter
        return self.default_splitter

    def _create_vector_store(self):
        return Chroma(
            collection_name=self.collection_name,
            embedding_function=get_embedding_model(),
            persist_directory=self.persist_directory,
            client_settings=Settings(anonymized_telemetry=False),
        )

    def get_retriever(self):
        return self.vector_store.as_retriever(search_kwargs={"k": chroma_conf['k']})

    def get_collection_count(self):
        return self.vector_store._collection.count()

    def _load_manifest(self) -> dict:
        if not os.path.exists(self.manifest_store):
            return {}
        try:
            with open(self.manifest_store, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f"读取知识库 manifest 失败，将按空 manifest 处理: {str(e)}")
            return {}

    def _save_manifest(self, manifest: dict):
        with open(self.manifest_store, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)

    @staticmethod
    def _manifest_item(md5_hex: str, chunk_count: int) -> dict:
        return {
            "md5": md5_hex,
            "chunk_count": chunk_count,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _sync_manifest_from_legacy_md5(self, manifest: dict):
        if manifest or not os.path.exists(self.md5_hex_store):
            return manifest
        try:
            with open(self.md5_hex_store, "r", encoding="utf-8") as f:
                legacy_md5s = {line.strip() for line in f if line.strip()}
        except Exception as e:
            logger.warning(f"读取旧 md5 文件失败，跳过兼容迁移: {str(e)}")
            return manifest

        allowed_files_path = listdir_with_allowed_type(
            get_abs_path(chroma_conf["data_path"]),
            tuple(chroma_conf["allow_knowledge_file_type"])
        )
        for path in allowed_files_path:
            md5_hex = get_file_md5_hex(path)
            if md5_hex in legacy_md5s:
                relative_source = os.path.relpath(path, get_abs_path(chroma_conf["data_path"]))
                manifest.setdefault(relative_source, self._manifest_item(md5_hex, 0))
        if manifest:
            self._save_manifest(manifest)
        return manifest

    @staticmethod
    def _build_chunk_id(source: str, chunk_index: int, content: str) -> str:
        digest = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
        return f"{source}:{chunk_index}:{digest}"

    def _delete_documents_by_source(self, source: str):
        try:
            self.vector_store.delete(where={"source": source})
        except Exception as e:
            logger.warning(f"按来源删除旧切片失败，source={source}, error={str(e)}")

    def _cleanup_stale_documents(self, allowed_files_path: tuple[str, ...]):
        existing_sources = {
            os.path.relpath(path, get_abs_path(chroma_conf["data_path"])) for path in allowed_files_path
        }
        manifest = self._sync_manifest_from_legacy_md5(self._load_manifest())
        try:
            stored = self.vector_store.get(include=["metadatas"])
        except Exception as e:
            logger.warning(f"读取向量库元数据失败，跳过陈旧切片清理: {str(e)}")
            stored = {"metadatas": []}

        stale_sources = set()
        for metadata in stored.get("metadatas", []):
            if not metadata:
                continue
            source = metadata.get("source")
            if source and source not in existing_sources:
                stale_sources.add(source)
        for source in list(manifest.keys()):
            if source not in existing_sources:
                stale_sources.add(source)

        for source in stale_sources:
            self._delete_documents_by_source(source)
            manifest.pop(source, None)
            logger.info(f"已清理已删除知识文件遗留的切片: {source}")
        self._save_manifest(manifest)

    def reset_store(self, clear_md5=True):
        """
        重建本地向量库，处理索引文件与元数据不一致的问题。
        """
        try:
            self.vector_store.delete_collection()
        except Exception as e:
            logger.warning(f"删除旧向量集合失败，将继续重建目录: {str(e)}")

        try:
            if os.path.exists(self.persist_directory):
                shutil.rmtree(self.persist_directory)
        except Exception as e:
            logger.warning(f"删除向量库目录失败: {str(e)}")

        os.makedirs(self.persist_directory, exist_ok=True)

        if clear_md5 and os.path.exists(self.md5_hex_store):
            try:
                os.remove(self.md5_hex_store)
            except Exception as e:
                logger.warning(f"删除md5去重文件失败: {str(e)}")
        if os.path.exists(self.manifest_store):
            try:
                os.remove(self.manifest_store)
            except Exception as e:
                logger.warning(f"删除知识库 manifest 失败: {str(e)}")

        self.vector_store = self._create_vector_store()
        logger.info("向量库重建完成")

    def load_document(self, force_reload=False):
        """
        从数据文件读取内容存放到向量数据库，计算md5进行去重
        :return:
        """
        def get_file_document(read_path):
            if read_path.endswith("txt"):
                return txt_loader(read_path)
            elif read_path.endswith("pdf"):
                return pdf_loader(read_path)
            return []

        allowed_files_path = listdir_with_allowed_type(
            get_abs_path(chroma_conf["data_path"]),
            tuple(chroma_conf["allow_knowledge_file_type"])
        )
        self._cleanup_stale_documents(allowed_files_path)
        manifest = self._sync_manifest_from_legacy_md5(self._load_manifest())

        for path in allowed_files_path:
            md5_hex = get_file_md5_hex(path)
            relative_source = os.path.relpath(path, get_abs_path(chroma_conf["data_path"]))
            if not force_reload and manifest.get(relative_source, {}).get("md5") == md5_hex:
                logger.info(f"文件{path}未发生变化，跳过加载")
                continue
            try:
                documents = get_file_document(path)
                if not documents:
                    logger.warning(f"文件{path}没有加载到任何文档，可能是格式不受支持")
                    continue
                documents = normalize_documents(documents)
                if relative_source.endswith("100问.txt") or "常见问题" in clean_text(documents[0].page_content[:80]):
                    documents = split_qa_documents(documents)
                for document in documents:
                    document.metadata["source"] = relative_source
                    document.metadata["source_type"] = os.path.splitext(path)[1].lstrip(".").lower()
                split_document = self._get_splitter(path).split_documents(documents)
                if not split_document:
                    logger.warning(f"文件{path}没有被切分成任何文档，可能是内容过短或切分参数不合适")
                    continue
                self._delete_documents_by_source(relative_source)
                for index, document in enumerate(split_document):
                    document.metadata["chunk_index"] = index
                ids = [
                    self._build_chunk_id(
                        relative_source,
                        index,
                        document.page_content,
                    )
                    for index, document in enumerate(split_document)
                ]
                # DashScope 单次 embedding 批量上限是 10，这里分批写入。
                batch_size = 10
                for i in range(0, len(split_document), batch_size):
                    self.vector_store.add_documents(
                        split_document[i:i + batch_size],
                        ids=ids[i:i + batch_size],
                    )
                manifest[relative_source] = self._manifest_item(md5_hex, len(split_document))
                self._save_manifest(manifest)
                logger.info(f"文件{path}已成功加载到向量数据库中")
            except Exception as e:
                # exec_info会详细记录报错堆栈
                logger.error(f"加载文件{path}到向量数据库失败: {str(e)}", exc_info=True)
                continue


if __name__ == '__main__':
    vs = VectorStoreService()
    vs.load_document()
    retriever = vs.get_retriever()
    res = retriever.invoke("迷路")
    for r in res:
        print(r.page_content)
