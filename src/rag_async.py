"""
异步 RAG 服务模块

在同步 RAG 服务（rag.py）基础上实现的异步版本，支持：
- 异步 LLM 调用（ainvoke / astream）
- 异步 Rerank API 调用（asyncio.to_thread 包装）
- 查询改写（Query Rewrite）集成
- 非阻塞的检索 + 生成管道

适用于高并发场景（如 FastAPI Web 服务）以及需要非阻塞操作的场景。
同时提供同步兼容包装器，兼容现有 Streamlit UI。
"""

import asyncio
from typing import AsyncIterator, Iterator

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableWithMessageHistory, RunnableLambda
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.vector_stores import VectorStoreService
from src.reranker import RerankerService
from src.bm25_retriever import BM25Retriever
from src.hybrid_retriever import HybridRetriever
from src.query_rewriter import QueryRewriter
from src import config_data as config


class AsyncRagService:
    """
    异步 RAG 服务

    支持异步调用链：查询改写 → 混合检索 → 重排序 → Parent-Child 展开 → LLM 生成。

    同时提供 sync_stream() / sync_invoke() 兼容方法，
    方便在 Streamlit 等同步框架中使用。

    Usage:
        # 异步方式（FastAPI 等）
        svc = AsyncRagService()
        async for chunk in svc.astream({"input": "..."}, config):
            print(chunk)

        # 同步兼容方式（Streamlit）
        svc = AsyncRagService()
        for chunk in svc.sync_stream({"input": "..."}, config):
            print(chunk)
    """

    def __init__(self, user_id: int = None):
        """
        初始化异步 RAG 服务和所有子组件。

        Args:
            user_id: 用户 ID，用于：
                     - 用户隔离的 Chroma collection（rag_user_{user_id}）
                     - MySQL 对话历史存储
                     None 时使用默认 collection 和文件历史（向后兼容）
        """
        self.user_id = user_id

        # --- 用户隔离：选择对应的 Chroma collection ---
        collection_name = None
        if user_id is not None:
            collection_name = config.get_user_collection_name(user_id)

        # --- 向量检索引擎 ---
        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model=config.embedding_model_name),
            collection_name=collection_name,
        )
        vector_retriever = self.vector_service.get_retriever()

        # --- BM25 + 混合检索 ---
        all_docs = self.vector_service.get_all_documents()
        bm25_retriever = BM25Retriever(all_docs)
        self.hybrid_retriever = HybridRetriever(vector_retriever, bm25_retriever)

        # --- 重排序 ---
        self.reranker = RerankerService()

        # --- 查询改写 ---
        self.query_rewriter = QueryRewriter()

        # --- LLM ---
        self.chat_model = ChatTongyi(model=config.chat_model_name)

        # --- Prompt ---
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", "请以我提供的已知参考资料为主，简洁和专业的回答用户问题。参考资料: {context}。"),
            ("system", "并且我提供用户的对话历史记录，如下："),
            MessagesPlaceholder("history"),
            ("user", "请回答用户提问：{input}")
        ])

        # --- 异步链 ---
        self.chain = self.__aget_chain()

    def __aget_chain(self):
        """
        构建异步 RAG 链。

        链结构:
            input
              → Query Rewrite（异步 LLM 扩展查询）
              → Hybrid Search（asyncio.to_thread 包装）
              → Rerank（异步 API 调用）
              → Parent-Child 展开
              → Prompt 模板
              → ChatTongyi 生成（astream）
              → 字符串输出
        """

        @RunnableLambda
        async def aretrieve_and_rerank(input_dict: dict) -> str:
            """
            异步检索 + 重排序 + Parent-Child 展开。

            完整流程:
                1. 查询改写（使用对话历史进行指代消解和扩展）
                2. 混合检索（向量 + BM25 → RRF 融合）
                3. 重排序（gte-rerank Cross-Encoder 精排）
                4. Parent-Child 展开 + 去重
                5. 拼接为最终 context
            """
            query = input_dict["input"]

            # Step 1: 查询改写（异步 LLM 调用）
            history = input_dict.get("history", None)
            rewritten_query = await self.query_rewriter.arewrite(query, history)

            # Step 2: 混合检索（CPU-bound → asyncio.to_thread）
            docs = await asyncio.to_thread(
                self.hybrid_retriever.retrieve, rewritten_query
            )

            # Step 3: 重排序（异步 API 调用）
            if docs:
                docs = await self.reranker.arerank(rewritten_query, docs)

            if not docs:
                return "无相关参考资料"

            # Step 4: Parent-Child 展开 + 去重
            seen_parents = set()
            parts = []
            for doc in docs:
                parent = doc.metadata.get("parent_content", "")
                title = doc.metadata.get("section_title", "")
                if parent and parent not in seen_parents:
                    seen_parents.add(parent)
                    if title:
                        parts.append(f"【{title}】\n{parent}")
                    else:
                        parts.append(parent)
                elif not parent:
                    parts.append(doc.page_content)

            return "\n\n---\n\n".join(parts)

        chain = (
            RunnablePassthrough.assign(context=aretrieve_and_rerank)
            | self.prompt_template
            | self.chat_model
            | StrOutputParser()
        )

        # --- 历史存储工厂（始终使用文件历史，避免 async/sync 桥接死锁）---
        # 注意：LangChain 的 RunnableWithMessageHistory 要求同步接口（messages / add_messages），
        # MySQL 历史需要在异步上下文中操作，若在此处做 async→sync 桥接会导致事件循环死锁。
        # 解决方案：RAG 链内部始终用文件历史（同步、可靠），
        # API 层单独管理 MySQL 历史（用于前端展示和跨设备查询）。
        def _get_history(session_id: str):
            from src.file_history_store import FileChatMessageHistory
            return FileChatMessageHistory(session_id)

        # 包装处理链以支持对话历史记录管理
        conversation_chain = RunnableWithMessageHistory(
            chain,                          # 基础处理链
            _get_history,                   # 历史工厂（闭包已捕获 user_id）
            input_messages_key="input",     # 输入消息的键名
            history_messages_key="history", # 历史消息的键名
        )

        return conversation_chain

    # ================================================================
    # 异步接口（用于 FastAPI / aiohttp 等异步框架）
    # ================================================================

    async def ainvoke(self, input_data: dict, session_config: dict) -> str:
        """
        异步调用（非流式），返回完整回答。

        Args:
            input_data: {"input": "用户查询"}
            session_config: {"configurable": {"session_id": "..."}}

        Returns:
            完整回答字符串
        """
        return await self.chain.ainvoke(input_data, session_config)

    async def astream(self, input_data: dict, session_config: dict) -> AsyncIterator[str]:
        """
        异步流式调用，逐个 token 产出。

        Args:
            input_data: {"input": "用户查询"}
            session_config: {"configurable": {"session_id": "..."}}

        Yields:
            生成的 token 字符串
        """
        async for chunk in self.chain.astream(input_data, session_config):
            yield chunk

    # ================================================================
    # 同步兼容接口（用于 Streamlit 等同步框架）
    # ================================================================

    def sync_invoke(self, input_data: dict, session_config: dict) -> str:
        """
        同步兼容包装器（非流式）。

        内部使用 asyncio.run() 调用异步链，
        适用于 Streamlit 等不支持原生 async/await 的框架。
        """
        return asyncio.run(self.ainvoke(input_data, session_config))

    def sync_stream(self, input_data: dict, session_config: dict) -> Iterator[str]:
        """
        同步兼容包装器（流式）。

        使用生产者-消费者模式将异步流桥接为同步生成器。
        启动一个后台线程运行异步事件循环，主线程通过队列消费结果。

        Args:
            input_data: {"input": "用户查询"}
            session_config: {"configurable": {"session_id": "..."}}

        Yields:
            生成的 token 字符串
        """
        import queue
        import threading

        q: queue.Queue = queue.Queue()

        async def producer():
            try:
                async for chunk in self.astream(input_data, session_config):
                    q.put(("chunk", chunk))
                q.put(("done", None))
            except Exception as e:
                q.put(("error", str(e)))

        def run_async_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(producer())
            loop.close()

        thread = threading.Thread(target=run_async_loop, daemon=True)
        thread.start()

        while True:
            msg_type, payload = q.get()
            if msg_type == "done":
                break
            elif msg_type == "error":
                yield f"[错误: {payload}]"
                break
            else:
                yield payload

        thread.join(timeout=5)


# ================================================================
# 测试入口
# ================================================================

async def _test_async():
    """异步测试函数。"""
    svc = AsyncRagService()
    session_config = config.build_session_config("test_async_user")
    print("=== 异步 RAG 测试 ===")
    async for chunk in svc.astream(
        {"input": "针织毛衣如何保养？"}, session_config
    ):
        print(chunk, end="", flush=True)
    print()


if __name__ == "__main__":
    asyncio.run(_test_async())
