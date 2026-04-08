import hashlib
import os
import re

from langchain_core.documents import Document

from utils.logger_handler import logger
from langchain_community.document_loaders import PyPDFLoader, TextLoader


def get_file_md5_hex(file_path: str):
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
    return PyPDFLoader(file_path=file_path, password=password).load()

def txt_loader(file_path):
    return TextLoader(file_path, encoding="utf-8").load()


def clean_text(text: str) -> str:
    if not text:
        return ""

    cleaned = text.replace("\ufeff", "").replace("\u3000", " ")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def normalize_documents(documents: list[Document]) -> list[Document]:
    normalized = []
    for document in documents:
        cleaned = clean_text(document.page_content)
        if not cleaned:
            continue
        document.page_content = cleaned
        normalized.append(document)
    return normalized


def split_qa_documents(documents: list[Document]) -> list[Document]:
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
