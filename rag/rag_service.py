"""
总结服务类：将用户提问和参考资料给模型进行总结回复
"""
import re
import threading

from rag.vector_store import VectorStoreService
from utils.config_handler import chroma_conf
from utils.prompt_loader import load_rag_prompts
from utils.logger_handler import logger
from langchain_core.prompts import PromptTemplate
from model.factory import get_chat_model
from langchain_core.output_parsers import StrOutputParser

class RagSummarizeService(object):
    """RAG 服务入口，负责检索、重排、总结和来源整理。"""

    def __init__(self):
        """初始化向量库、提示词链路和检索相关参数。"""
        self.vector_store = VectorStoreService()
        self._collection_ready_checked = False
        self._repair_lock = threading.Lock()
        self.prompt_text = load_rag_prompts()
        self.prompt_template = PromptTemplate.from_template(self.prompt_text)
        self.model = get_chat_model()
        self.chain = self._init_chain()
        self.top_k = chroma_conf["k"]
        self.candidate_k = chroma_conf.get("candidate_k", max(self.top_k * 2, self.top_k))
        self.min_relevance_score = chroma_conf.get("min_relevance_score", 0.0)
        self.synonym_map = {
            "不回充": ["回充失败", "无法返回充电座", "找不到充电座"],
            "回不了充": ["回充失败", "无法返回充电座"],
            "迷路": ["定位异常", "建图异常", "导航异常"],
            "漏扫": ["清扫遗漏", "覆盖率低"],
            "水痕": ["拖地水痕", "拖布湿度", "地面残留水渍"],
            "缠头发": ["毛发缠绕", "边刷缠绕", "主刷缠绕"],
            "噪音大": ["异响", "噪声异常"],
            "不出水": ["拖地不出水", "水箱异常"],
            "卡住": ["脱困失败", "避障失败"],
        }
        self.stopwords = {
            "的", "了", "呢", "吗", "呀", "啊", "我", "想", "请问", "一下", "怎么", "怎样",
            "是否", "一个", "这个", "那个", "可以", "需要", "有没有", "如何", "机器人", "扫地机器人",
        }

    def _init_chain(self):
        """构造“提示词 -> 模型 -> 文本解析”的最小总结链。"""
        chain = self.prompt_template | self.model | StrOutputParser()
        return chain

    def _ensure_collection_ready(self):
        """
        向量库为空时自动触发一次本地知识入库，避免首次使用直接空检索。
        """
        if self._collection_ready_checked:
            return
        self._collection_ready_checked = True

        try:
            current_count = self.vector_store.vector_store._collection.count()
        except Exception as e:
            logger.error(f"获取向量库文档数量失败: {str(e)}", exc_info=True)
            return

        if current_count > 0:
            logger.info(f"当前向量库已有文档，数量: {current_count}")
            return

        logger.warning("检测到向量库为空，开始自动加载知识文档")
        try:
            self.vector_store.load_document()
            latest_count = self.vector_store.vector_store._collection.count()
            logger.info(f"自动加载完成，当前向量库文档数量: {latest_count}")
        except Exception as e:
            logger.error(f"自动加载知识文档失败: {str(e)}", exc_info=True)

    @staticmethod
    def _is_corrupted_index_error(error: Exception) -> bool:
        message = str(error).lower()
        return (
            "hnsw segment reader" in message
            or "nothing found on disk" in message
            or "error executing plan" in message
        )

    def _repair_vector_store(self):
        """在检测到索引损坏时，串行重建向量库，避免并发修复。"""
        with self._repair_lock:
            logger.warning("检测到向量索引异常，开始重建向量库")
            self.vector_store.reset_store(clear_md5=True)
            self.vector_store.load_document(force_reload=True)
            self._collection_ready_checked = True
            latest_count = self.vector_store.get_collection_count()
            logger.info(f"向量库重建完成，当前文档数量: {latest_count}")

    @staticmethod
    def _normalize_query(query: str) -> str:
        """对用户问题做轻量规范化，统一一些常见别名。"""
        normalized = re.sub(r"\s+", " ", query.strip().lower())
        replacements = {
            "扫拖一体": "扫拖一体机器人",
            "回充座": "充电座",
            "基站": "充电座",
            "回基站": "回充",
        }
        for source, target in replacements.items():
            normalized = normalized.replace(source, target)
        return normalized

    def _expand_query(self, query: str) -> str:
        """把口语化问题扩展成更适合检索的表达。"""
        normalized = self._normalize_query(query)
        expansions = []
        for phrase, candidates in self.synonym_map.items():
            if phrase in normalized:
                expansions.extend(candidates)
        if expansions:
            normalized = f"{normalized} {' '.join(expansions)}"
        return normalized

    def _query_terms(self, query: str) -> set[str]:
        """提取检索关键词，供后续重排计算覆盖率。"""
        expanded = self._expand_query(query)
        terms = set()
        for term in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]+", expanded):
            if term not in self.stopwords:
                terms.add(term)
        return terms

    @staticmethod
    def _document_terms(content: str) -> set[str]:
        """把文档内容切成词项集合，便于和 query 做简单交集比较。"""
        return set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]+", content.lower()))

    def _rerank_score(self, query_terms: set[str], content: str, relevance_score: float) -> float:
        """
        组合向量分数和关键词覆盖率。

        这里不是完整 reranker，而是一个成本很低的启发式重排，
        用来避免“向量相似但关键词没对上”的片段排得过高。
        """
        doc_terms = self._document_terms(content)
        overlap = len(query_terms & doc_terms)
        coverage = overlap / max(len(query_terms), 1)
        return relevance_score * 0.7 + coverage * 0.3

    def retriever_docs(self, query):
        """执行检索主流程：查询扩展 -> 候选召回 -> 轻量重排 -> 截断返回。"""
        self._ensure_collection_ready()
        expanded_query = self._expand_query(query)
        query_terms = self._query_terms(query)
        try:
            candidates = self.vector_store.vector_store.similarity_search_with_relevance_scores(
                expanded_query,
                k=self.candidate_k,
            )
        except Exception as e:
            logger.error(f"向量检索失败: {str(e)}", exc_info=True)
            if self._is_corrupted_index_error(e):
                try:
                    self._repair_vector_store()
                    candidates = self.vector_store.vector_store.similarity_search_with_relevance_scores(
                        expanded_query,
                        k=self.candidate_k,
                    )
                except Exception as repair_error:
                    logger.error(f"重建后检索仍失败: {str(repair_error)}", exc_info=True)
                    return []
            else:
                return []

        # 先保留候选，再按自定义分数重新排序。
        scored_docs = []
        for doc, relevance_score in candidates:
            if relevance_score < self.min_relevance_score:
                continue
            rerank_score = self._rerank_score(query_terms, doc.page_content, relevance_score)
            doc.metadata["relevance_score"] = round(float(relevance_score), 4)
            doc.metadata["rerank_score"] = round(float(rerank_score), 4)
            scored_docs.append((doc, rerank_score))

        scored_docs.sort(key=lambda item: item[1], reverse=True)
        docs = [doc for doc, _ in scored_docs[: self.top_k]]
        logger.info(
            f"RAG检索完成，原始query={query}，扩展query={expanded_query}，候选数={len(candidates)}，入选数={len(docs)}"
        )
        return docs

    @staticmethod
    def _format_references(docs) -> str:
        """把命中的来源整理成回答尾部可展示的引用列表。"""
        references = []
        seen = set()
        for doc in docs:
            source = doc.metadata.get("source", "未知来源")
            page = doc.metadata.get("page")
            ref = f"{source} 第{page + 1}页" if isinstance(page, int) else source
            if ref not in seen:
                seen.add(ref)
                references.append(ref)
        if not references:
            return ""
        return "\n参考来源：\n- " + "\n- ".join(references)

    def rag_summarize(self, query):
        """对外暴露的 RAG 总入口，返回“总结结果 + 引用来源”。"""
        try:
            context_docs = self.retriever_docs(query)
        except Exception as e:
            logger.error(f"RAG检索流程异常: {str(e)}", exc_info=True)
            return "知识库检索暂时不可用，请稍后重试。"

        if not context_docs:
            return "未检索到相关参考资料。"

        # 把命中文档拼成可追踪来源的上下文，便于模型总结时引用。
        context_parts = []
        for counter, doc in enumerate(context_docs, start=1):
            source = doc.metadata.get("source", "未知来源")
            page = doc.metadata.get("page")
            chunk_index = doc.metadata.get("chunk_index")
            location_parts = [f"来源={source}"]
            if page is not None:
                location_parts.append(f"页码={page}")
            if chunk_index is not None:
                location_parts.append(f"切片={chunk_index}")
            context_parts.append(
                f"[参考资料{counter}] {' | '.join(location_parts)}\n{doc.page_content.strip()}"
            )
        context = "\n\n".join(context_parts)
        try:
            answer = self.chain.invoke(
                {
                    "input": query,
                    "context": context,
                }
            )
            return answer.strip() + self._format_references(context_docs)
        except Exception as e:
            logger.error(f"RAG总结失败: {str(e)}", exc_info=True)
            return "知识总结暂时不可用，请稍后重试。"


if __name__ == '__main__':
    rag = RagSummarizeService()
    print(rag.rag_summarize("小户型适合什么扫地机器人"))
