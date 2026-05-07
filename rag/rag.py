from typing import Iterable

from langchain_community.chat_models import ChatTongyi
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import (
    RunnableLambda,
    RunnablePassthrough,
    RunnableWithMessageHistory,
)

import config_data as config
from file_history import get_history
from vector_stores import VectorStoreService


class RagService:
    def __init__(self):
        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model=config.embedding_model_name)
        )
        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "请严格基于我提供的参考资料回答用户问题。"
                    "如果参考资料不足以支持结论，不要补充猜测，只能明确说明无法从知识库中找到答案。",
                ),
                ("system", "参考资料如下:\n{context}"),
                ("system", "以下是用户的历史对话记录:"),
                MessagesPlaceholder("history"),
                ("user", "请回答用户问题: {input}"),
            ]
        )
        self.chat_model = ChatTongyi(model=config.chat_model_name)
        self.chain = self._build_chain()

    def search_documents(self, query: str) -> list[Document]:
        scored_docs = self.vector_service.similarity_search_with_relevance_scores(query)
        filtered_docs = []
        for doc, score in scored_docs:
            if score >= config.retrieval_score_threshold:
                doc.metadata["relevance_score"] = round(score, 4)
                filtered_docs.append(doc)
        return filtered_docs

    def answer_question(
        self,
        query: str,
        session_config: dict,
    ) -> tuple[Iterable[str] | None, list[Document], str | None]:
        source_docs = self.search_documents(query)
        if not source_docs:
            return (
                None,
                [],
                "知识库中没有找到足够相关的内容，我现在不能基于现有资料回答这个问题。",
            )

        return self.chain.stream({"input": query}, session_config), source_docs, None

    def _build_chain(self):
        retriever = self.vector_service.get_retriever()

        def format_document(documents: list[Document]) -> str:
            formatted_docs = []
            for doc in documents:
                formatted_docs.append(
                    f"文档片段: {doc.page_content}\n文档元数据: {doc.metadata}"
                )
            return "\n\n".join(formatted_docs)

        def format_for_retriever(value: dict) -> str:
            return value["input"]

        def format_for_template(value: dict) -> dict:
            return {
                "input": value["input"]["input"],
                "context": value["context"],
                "history": value["input"]["chat_history"],
            }

        chain = (
            {
                "input": RunnablePassthrough(),
                "context": RunnableLambda(format_for_retriever)
                | retriever
                | RunnableLambda(format_document),
            }
            | RunnableLambda(format_for_template)
            | self.prompt_template
            | self.chat_model
            | StrOutputParser()
        )

        return RunnableWithMessageHistory(
            chain,
            get_history,
            input_messages_key="input",
            history_messages_key="chat_history",
        )


if __name__ == "__main__":
    session_config = config.build_session_config("debug_user")
    stream, source_docs, fallback = RagService().answer_question(
        "春天穿什么颜色?",
        session_config,
    )
    if fallback:
        print(fallback)
    else:
        print("命中文档数:", len(source_docs))
        print("".join(stream))
