import os, hashlib
from utils.logger_handler import logger
from langchain_core.documents import Document
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
        return allowed_types

    for f in os.listdir(path):
        if f.endswith(allowed_types):
            files.append(os.path.join(path, f))

    return tuple(files)

def pdf_loader(file_path, password=None):
    return PyPDFLoader(file_path=file_path, password=password).load()

def txt_loader(file_path):
    return TextLoader(file_path, encoding="utf-8").load()