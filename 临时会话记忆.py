from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import InMemoryChatMessageHistory

from 长期会话记忆 import FileChatMessageHistory

model = ChatTongyi(model="qwen3-max")
prompt = PromptTemplate.from_template(
    "根据历史会话回答用户问题.对话历史：{chat_history}, 用户提问:{input}, 请回答"
)
str_parser = StrOutputParser()
base_chain = prompt | model | str_parser
store = {}


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
