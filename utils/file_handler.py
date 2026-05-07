import hashlib
import os
import re

from langchain_core.documents import Document

from utils.logger_handler import logger
from langchain_community.document_loaders import PyPDFLoader, TextLoader


def get_file_md5_hex(file_path: str):
    """计算文件 md5，用于知识库增量入库判断。"""
    if not os.path.exists(file_path):
        logger.error(f"文件不存在: {file_path}")
        return None
    if not os.path.isfile(file_path):
        logger.error(f"路径不是一个文件: {file_path}")
        return None
    md5_obj = hashlib.md5()
    chunk_size = 4096
    try:
        with open(file_path, 'rb') as f:
            while chunk := f.read(chunk_size):
                md5_obj.update(chunk)
            md5_hex = md5_obj.hexdigest()
            return md5_hex
    except Exception as e:
        logger.error(f"计算文件{file_path}md5失败, {str(e)}")
        return None


def listdir_with_allowed_type(path, allowed_types):
    """递归扫描目录，只返回允许后缀的文件。"""
    files = []
    if not os.path.isdir(path):
        logger.error(f"路径不是一个目录: {path}")
        return tuple()

    for root, _, filenames in os.walk(path):
        for filename in filenames:
            if filename.endswith(allowed_types):
                files.append(os.path.join(root, filename))

    return tuple(sorted(files))

def pdf_loader(file_path, password=None):
    """加载 PDF 文件并转成 LangChain Document 列表。"""
    return PyPDFLoader(file_path=file_path, password=password).load()

def txt_loader(file_path):
    """加载 UTF-8 文本文件并转成 LangChain Document 列表。"""
    return TextLoader(file_path, encoding="utf-8").load()


def clean_text(text: str) -> str:
    """做轻量文本清洗，统一空白、换行和 BOM。"""
    if not text:
        return ""

    cleaned = text.replace("\ufeff", "").replace("\u3000", " ")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def normalize_documents(documents: list[Document]) -> list[Document]:
    """对一组文档做统一清洗，并过滤空内容。"""
    normalized = []
    for document in documents:
        cleaned = clean_text(document.page_content)
        if not cleaned:
            continue
        document.page_content = cleaned
        normalized.append(document)
    return normalized


def split_qa_documents(documents: list[Document]) -> list[Document]:
    """
    把 FAQ/问答类长文本拆成独立的“问题-答案”文档。

    这样做的目标是提升知识库命中率，避免一整个 FAQ 文件被当成长文切碎后难以命中。
    """
    qa_documents = []
    pattern = re.compile(
        r"(?ms)(?:^|\n)(?:\d+\.\s*)?(?:\*\*)?(?P<question>[^\n？?]{3,}[？?])(?:\*\*)?\s*\n-\s*(?P<answer>.*?)(?=(?:\n(?:\d+\.\s*)?(?:\*\*)?[^\n？?]{3,}[？?](?:\*\*)?\s*\n-\s)|\Z)"
    )

    for document in documents:
        matches = list(pattern.finditer(document.page_content))
        if len(matches) < 3:
            qa_documents.append(document)
            continue

        for index, match in enumerate(matches):
            question = clean_text(match.group("question"))
            answer = clean_text(match.group("answer"))
            if not question or not answer:
                continue
            qa_documents.append(
                Document(
                    page_content=f"问题：{question}\n答案：{answer}",
                    metadata={**document.metadata, "qa_index": index},
                )
            )

    return qa_documents
