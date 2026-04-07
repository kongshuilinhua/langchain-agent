from abc import ABC, abstractmethod
from typing import Optional, Union
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models.tongyi import ChatTongyi
from utils.config_handler import rag_conf

class BaseModelFactory(ABC):
    @abstractmethod
    def generate(self) -> Optional[Union[Embeddings, BaseChatModel]]:
        pass

class ChatModelFactory(BaseModelFactory):
    def generate(self) -> Optional[Union[Embeddings, BaseChatModel]]:
        return ChatTongyi(model=rag_conf['chat_model_name'])

class EmbeddingsFactory(BaseModelFactory):
    def generate(self) -> Optional[Union[Embeddings, BaseChatModel]]:
        return DashScopeEmbeddings(model=rag_conf['embedding_model_name'])

chat_model = ChatModelFactory().generate()
embedding_model = EmbeddingsFactory().generate()
