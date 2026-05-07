import os, json
from typing import Sequence

from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import message_to_dict, messages_from_dict, BaseMessage
from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableWithMessageHistory


class FileChatMessageHistory(BaseChatMessageHistory):
    def __init__(self, session_id, storage_path):
        self.session_id = session_id
        self.storage_path = storage_path
        self.file_path = os.path.join(self.storage_path, self.session_id)
        # 创建存储目录（如果不存在）
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        all_messages = list(self.messages)
        all_messages.extend(messages)
        new_messages = [message_to_dict(d) for d in all_messages]
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(new_messages, f)

    @property
    def messages(self) -> list[BaseMessage]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                messages_data = json.load(f)
                return messages_from_dict(messages_data)
        except FileNotFoundError:
            return []

    def clear(self) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump([], f)


model = ChatTongyi(model="qwen3-max")
prompt = PromptTemplate.from_template(
    "根据历史会话回答用户问题.对话历史：{chat_history}, 用户提问:{input}, 请回答"
)
str_parser = StrOutputParser()
base_chain = prompt | model | str_parser


def get_history(session_id):
    return FileChatMessageHistory(session_id, "./chat_history")


conversation_chain = RunnableWithMessageHistory(
    base_chain,
    get_history,
    input_messages_key="input",
    history_messages_key="chat_history"
)

session_config = {
    "configurable": {
        "session_id": "user001"
    }
}
res = conversation_chain.invoke({"input": "蜂蜜和蜜蜂"}, session_config)
res2 = conversation_chain.invoke({"input": "牛奶和奶牛"}, session_config)
res3 = conversation_chain.invoke({"input": "类似的还有？名称是回文串，物品还相关"}, session_config)
print(res3)
