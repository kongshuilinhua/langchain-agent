from langchain_chroma import Chroma
from chromadb.config import Settings
from utils.config_handler import chroma_conf
from model.factory import embedding_model
from langchain_text_splitters import RecursiveCharacterTextSplitter
from utils.path_tool import get_abs_path
import os
from utils.file_handler import *


class VectorStoreService:
    def __init__(self):
        self.persist_directory = get_abs_path(chroma_conf['persist_directory'])
        os.makedirs(self.persist_directory, exist_ok=True)
        # 关闭 Chroma 匿名遥测，避免无关 telemetry 报错干扰。
        os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
        self.vector_store = Chroma(
            collection_name=chroma_conf['collection_name'],
            embedding_function=embedding_model,
            persist_directory=self.persist_directory,
            client_settings=Settings(anonymized_telemetry=False),
        )
        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf['chunk_size'],
            chunk_overlap=chroma_conf['chunk_overlap'],
            separators=chroma_conf['separators'],
            length_function=len,
        )

    def get_retriever(self):
        return self.vector_store.as_retriever(search_kwargs={"k": chroma_conf['k']})

    def load_document(self):
        """
        从数据文件读取内容存放到向量数据库，计算md5进行去重
        :return:
        """
        def check_md5_hex(md5_for_check):
            if not os.path.exists(get_abs_path(chroma_conf['md5_hex_store'])):
                # 创建文件
                open(get_abs_path(chroma_conf['md5_hex_store']), 'w', encoding="utf-8").close()
                return False
            with open(get_abs_path(chroma_conf['md5_hex_store']), encoding="utf-8") as f:
                for line in f.readlines():
                    line = line.strip()
                    if line == md5_for_check:
                        return True
            return False

        def save_md5_hex(md5_for_check):
            with open(get_abs_path(chroma_conf['md5_hex_store']), "a", encoding="utf-8") as f:
                f.write(md5_for_check + "\n")

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

        for path in allowed_files_path:
            md5_hex = get_file_md5_hex(path)
            if check_md5_hex(md5_hex):
                logger.info(f"文件{path}已存在于向量数据库中，跳过加载")
                continue
            try:
                documents = get_file_document(path)
                if not documents:
                    logger.warning(f"文件{path}没有加载到任何文档，可能是格式不受支持")
                    continue
                split_document = self.spliter.split_documents(documents)
                if not split_document:
                    logger.warning(f"文件{path}没有被切分成任何文档，可能是内容过短或切分参数不合适")
                    continue
                # DashScope 单次 embedding 批量上限是 10，这里分批写入。
                batch_size = 10
                for i in range(0, len(split_document), batch_size):
                    self.vector_store.add_documents(split_document[i:i + batch_size])
                save_md5_hex(md5_hex)
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
