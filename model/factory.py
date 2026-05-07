import os
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Optional, Union

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models.tongyi import ChatTongyi
from utils.config_handler import rag_conf


class BaseModelFactory(ABC):
    """模型工厂抽象基类。"""

    @abstractmethod
    def generate(self) -> Optional[Union[Embeddings, BaseChatModel]]:
        pass


class ChatModelFactory(BaseModelFactory):
    """聊天模型工厂。"""

    def generate(self) -> Optional[Union[Embeddings, BaseChatModel]]:
        return ChatTongyi(model=rag_conf['chat_model_name'])


class EmbeddingsFactory(BaseModelFactory):
    """向量模型工厂。"""

    def generate(self) -> Optional[Union[Embeddings, BaseChatModel]]:
        return DashScopeEmbeddings(model=rag_conf['embedding_model_name'])


def _require_dashscope_api_key() -> None:
    """在真正初始化模型前检查密钥，避免 import 阶段静默失败。"""
    if not os.getenv("DASHSCOPE_API_KEY"):
        raise EnvironmentError("缺少环境变量 DASHSCOPE_API_KEY，无法初始化模型。")


@lru_cache(maxsize=1)
def get_chat_model() -> BaseChatModel:
    """惰性获取聊天模型，并通过缓存避免重复初始化。"""
    _require_dashscope_api_key()
    return ChatModelFactory().generate()


@lru_cache(maxsize=1)
def get_embedding_model() -> Embeddings:
    """惰性获取 embedding 模型，并通过缓存避免重复初始化。"""
    _require_dashscope_api_key()
    return EmbeddingsFactory().generate()
