"""
重排序服务模块

该模块提供了基于阿里云 DashScope API 的文档重排序功能。
在 RAG 系统中，重排序用于对检索到的文档进行相关性重新排序，
以提高最终返回结果的质量。

支持同步和异步调用。
"""

import asyncio
from langchain_core.documents import Document
from dashscope.rerank.text_rerank import TextReRank
from src import config_data as config


class RerankerService:
    """
    重排序服务类
    
    使用阿里云 DashScope 的重排序 API 对检索到的文档进行相关性排序，
    筛选出与查询最相关的 top_n 个文档。
    
    Attributes:
        model_name (str): 重排序模型的名称，默认从配置文件读取
    """
    
    def __init__(self, model_name: str = config.reranker_model_name):
        """
        初始化重排序服务
        
        Args:
            model_name (str): 重排序模型名称，默认为配置中的 reranker_model_name
        """
        self.model_name = model_name

    def rerank(self, query: str, docs: list[Document], top_n: int = config.reranker_top_n) -> list[Document]:
        """
        对文档列表进行重排序
        
        根据查询语句对文档进行相关性评分和排序，返回最相关的 top_n 个文档。
        
        Args:
            query (str): 用户查询语句
            docs (list[Document]): 待排序的文档列表
            top_n (int): 返回的最相关文档数量，默认从配置文件读取
            
        Returns:
            list[Document]: 按相关性排序后的文档列表（最多 top_n 个）
            
        Note:
            - 如果文档列表为空，返回空列表
            - 如果文档数量小于等于 top_n，直接返回原文档列表
            - 如果 API 调用失败，降级返回前 top_n 个文档
        """
        # 边界情况：空文档列表
        if not docs:
            return []
        
        # 如果文档数量已经少于或等于需要的数量，无需重排序
        if len(docs) <= top_n:
            return docs

        # 提取文档内容用于 API 调用
        documents = [doc.page_content for doc in docs]

        # 调用阿里云 DashScope 重排序 API
        result = TextReRank.call(
            model=self.model_name,
            query=query,
            documents=documents,
            top_n=top_n,
            return_documents=False,
        )

        # 检查 API 调用是否成功
        if result.status_code != 200:
            print(f"Rerank API error: {result.code} - {result.message}")
            # 降级策略：API 失败时返回前 top_n 个文档
            return docs[:top_n]

        # 根据 API 返回的索引重建排序后的文档列表
        reranked = []
        for item in result.output.results:
            idx = item.index
            # 确保索引有效，防止越界
            if idx < len(docs):
                reranked.append(docs[idx])

        return reranked

    async def arerank(
        self, query: str, docs: list[Document], top_n: int = None
    ) -> list[Document]:
        """
        异步版本：对文档列表进行重排序。

        使用 asyncio.to_thread 将同步 API 调用包装为异步操作，
        避免阻塞事件循环。

        Args:
            query: 用户查询语句
            docs: 待排序的文档列表
            top_n: 返回的最相关文档数量

        Returns:
            按相关性排序后的文档列表
        """
        top_n = top_n or config.reranker_top_n
        return await asyncio.to_thread(self.rerank, query, docs, top_n)


if __name__ == "__main__":
    # 测试代码
    svc = RerankerService()
    test_docs = [
        Document(page_content="test doc 1", metadata={"source": "a"}),
        Document(page_content="test doc 2", metadata={"source": "b"}),
    ]
    result = svc.rerank("test query", test_docs, top_n=1)
    print(result)
