"""
异步 RAG 服务模块 — LangGraph 版本

使用 LangGraph StateGraph + AsyncSqliteSaver 替代已弃用的
RunnableWithMessageHistory，实现对话历史的持久化和自动管理。

核心架构:
  StateGraph(RagState)
    ├── classify_query 节点: 问题分类（chat/faq/knowledge）
    ├── retrieve 节点: 查询改写 → 混合检索 → 重排序 → Parent-Child 展开
    ├── evaluate_retrieval 节点: 检索质量评估
    ├── rewrite_query 节点: 查询改写重试
    ├── generate 节点: 提示词模板 + LLM 生成
    ├── direct_answer 节点: 闲聊直接回答
    └── AsyncSqliteSaver: SQLite 持久化对话历史（用户隔离）

流式生成:
  使用 graph.astream(stream_mode="messages") 实现 token 级别流式输出。

Usage:
    svc = AsyncRagService(user_id=1)
    async for chunk in svc.astream({"input": "..."}, config):
        print(chunk)
"""

import asyncio
import os
from typing import TypedDict, Annotated, AsyncIterator

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from typing_extensions import Literal

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, AIMessageChunk
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.retrieval import VectorStoreService
from src.retrieval import RerankerService
from src.retrieval import BM25Retriever
from src.retrieval import HybridRetriever
from src.rag.rewriter import QueryRewriter
import src.config as config

# ---- 持久化根目录（使用 config 统一路径）----
STORAGE_ROOT = config.chat_history_path


# ================================================================
# LangGraph State
# ================================================================

class RagState(TypedDict):
    """RAG 图状态。

    Attributes:
        messages: 对话历史，由 checkpointer 自动加载/保存，
                  add_messages reducer 负责合并新消息。
        context: 当前查询检索到的参考资料文本，
                 由 retrieve 节点写入，generate 节点读取。
        query_type: 查询类型分类（knowledge/chat/faq），
                    由 classify_query 节点写入，用于条件路由。
        retrieval_quality: 检索质量评分（0-1），
                          由 evaluate_retrieval 节点写入，决定是否重试。
        retry_count: 重试次数，防止无限循环。
    """
    messages: Annotated[list[BaseMessage], add_messages]
    context: str
    query_type: str
    retrieval_quality: float
    retry_count: int


# ================================================================
# AsyncRagService
# ================================================================

class AsyncRagService:
    """异步 RAG 服务（LangGraph 后端）。

    使用 LangGraph StateGraph 管理 RAG 管线，
    AsyncSqliteSaver 提供对话历史的持久化存储。

    每个用户使用独立的 SQLite 数据库文件，实现物理级别的用户隔离。
    """

    def __init__(self, user_id: int = None):
        """初始化异步 RAG 服务和所有子组件。

        Args:
            user_id: 用户 ID，用于：
                     - 用户隔离的 Chroma collection（rag_user_{user_id}）
                     - 用户隔离的 SQLite checkpoint 数据库
                     None 时使用默认 collection 和共享 checkpoint（向后兼容）
        """
        self.user_id = user_id

        # ---- 用户隔离：Chroma collection ----
        collection_name = None
        if user_id is not None:
            collection_name = config.get_user_collection_name(user_id)

        # ---- 向量检索引擎 ----
        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model=config.embedding_model_name),
            collection_name=collection_name,
        )
        vector_retriever = self.vector_service.get_retriever()

        # ---- BM25 + 混合检索 ----
        all_docs = self.vector_service.get_all_documents()
        bm25_retriever = BM25Retriever(all_docs)
        self.hybrid_retriever = HybridRetriever(vector_retriever, bm25_retriever)

        # ---- 重排序 ----
        self.reranker = RerankerService()

        # ---- 查询改写 ----
        self.query_rewriter = QueryRewriter()

        # ---- LLM（streaming=True 以支持 stream_mode="messages"）----
        self.chat_model = ChatTongyi(
            model=config.chat_model_name,
            streaming=True,
        )

        # ---- 提示词模板 ----
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", "请以我提供的已知参考资料为主，简洁和专业的回答用户问题。参考资料: {context}。"),
            ("system", "并且我提供用户的对话历史记录，如下："),
            MessagesPlaceholder("history"),
            ("user", "请回答用户提问：{input}"),
        ])

        # ---- Graph（延迟编译，checkpointer 需要异步初始化）----
        self._graph = None
        self._checkpointer_conn = None
        self._checkpointer = None

        # ---- 用户隔离：SQLite checkpoint 数据库路径 ----
        db_name = f"checkpoints_user_{user_id}.db" if user_id is not None else "checkpoints_default.db"
        self._checkpoint_db_path = os.path.join(STORAGE_ROOT, db_name)
        os.makedirs(os.path.dirname(self._checkpoint_db_path), exist_ok=True)

    # ================================================================
    # Graph 构建
    # ================================================================

    def _build_graph(self) -> StateGraph:
        """构建 LangGraph StateGraph（不编译）。

        真正的 LangGraph 优势体现：
        1. 条件路由：根据问题类型选择不同路径
        2. 质量评估：检索后判断是否需要重新检索
        3. 循环重试：检索质量差时自动改写查询并重试（最多2次）
        4. 智能降级：FAQ 命中则无需检索知识库

        Returns:
            未编译的 StateGraph，等待 checkpointer 注入。
        """
        graph = StateGraph(RagState)

        # 添加节点
        graph.add_node("classify_query", self._classify_query_node)
        graph.add_node("retrieve", self._retrieve_node)
        graph.add_node("evaluate_retrieval", self._evaluate_retrieval_node)
        graph.add_node("rewrite_query", self._rewrite_query_node)
        graph.add_node("generate", self._generate_node)
        graph.add_node("direct_answer", self._direct_answer_node)

        # 边连接
        graph.add_edge(START, "classify_query")
        
        # 条件路由：根据问题类型分流
        graph.add_conditional_edges(
            "classify_query",
            self._route_by_query_type,
            {
                "chat": "direct_answer",
                "faq": "retrieve",  # FAQ 也可以走检索增强
                "knowledge": "retrieve",
            }
        )
        
        # 检索后评估质量
        graph.add_edge("retrieve", "evaluate_retrieval")
        
        # 条件路由：根据检索质量决定下一步
        graph.add_conditional_edges(
            "evaluate_retrieval",
            self._route_by_retrieval_quality,
            {
                "good": "generate",
                "retry": "rewrite_query",
            }
        )
        
        # 改写后重新检索（形成循环）
        graph.add_edge("rewrite_query", "retrieve")
        
        # 生成后结束
        graph.add_edge("generate", END)
        graph.add_edge("direct_answer", END)

        return graph
    
    def _route_by_query_type(self, state: RagState) -> Literal["chat", "faq", "knowledge"]:
        """根据问题类型路由到不同节点。"""
        return state.get("query_type", "knowledge")
    
    def _route_by_retrieval_quality(self, state: RagState) -> Literal["good", "retry"]:
        """根据检索质量路由：好则生成，差则重试。"""
        quality = state.get("retrieval_quality", 0)
        retry_count = state.get("retry_count", 0)
        
        # 质量足够或已达最大重试次数，进入生成
        if quality >= 0.6 or retry_count >= 2:
            return "good"
        else:
            return "retry"

    async def _ensure_graph(self):
        """延迟初始化：创建 checkpointer 并编译 graph。

        AsyncSqliteSaver 需要异步连接 aiosqlite，无法在同步 __init__ 中完成。
        首次调用 astream/ainvoke 时自动触发初始化。

        Returns:
            编译后的 CompiledGraph
        """
        if self._graph is not None:
            return self._graph

        import aiosqlite

        # 建立 SQLite 异步连接
        self._checkpointer_conn = await aiosqlite.connect(self._checkpoint_db_path)

        # 创建 AsyncSqliteSaver
        self._checkpointer = AsyncSqliteSaver(self._checkpointer_conn)

        # 编译 graph
        self._graph = self._build_graph().compile(checkpointer=self._checkpointer)

        return self._graph

    # ================================================================
    # Graph 节点
    # ================================================================

    async def _classify_query_node(self, state: RagState) -> dict:
        """分类节点：判断用户问题类型。
        
        使用 LLM 快速分类问题类型：
        - chat: 闲聊、问候、感谢等（无需检索）
        - faq: 常见问题（营业时问、退换货等）
        - knowledge: 需要检索知识库的专业问题
        
        Args:
            state: 当前图状态
            
        Returns:
            {"query_type": "chat|faq|knowledge", "retry_count": 0}
        """
        messages = state.get("messages", [])
        if not messages:
            return {"query_type": "knowledge", "retry_count": 0}
        
        query = messages[-1].content if hasattr(messages[-1], "content") else str(messages[-1])
        
        # 简单规则分类（也可以用 LLM，但为了速度先用规则）
        query_lower = query.lower()
        
        # 闲聊检测
        chat_keywords = ["你好", "您好", "hi", "hello", "谢谢", "感谢", "再见", "拜拜"]
        if any(kw in query_lower for kw in chat_keywords):
            return {"query_type": "chat", "retry_count": 0}
        
        # FAQ 检测
        faq_keywords = ["营业时间", "退换货", "发货", "配送", "支付", "发票", "售后", "尺码"]
        if any(kw in query for kw in faq_keywords):
            return {"query_type": "faq", "retry_count": 0}
        
        # 默认为知识问答
        return {"query_type": "knowledge", "retry_count": 0}
    
    async def _direct_answer_node(self, state: RagState) -> dict:
        """直接回答节点：处理闲聊或简单问题，无需检索。
        
        Args:
            state: 当前图状态
            
        Returns:
            {"messages": [AIMessage]} — 直接生成的回答
        """
        messages = state.get("messages", [])
        if not messages:
            return {"messages": []}
        
        current_query = messages[-1].content if messages else ""
        
        # 简单的友好回复模板
        direct_prompt = ChatPromptTemplate.from_messages([
            ("system", "你是一个友好的客服助手。用户正在与你闲聊或提出简单问题，请友好、简洁地回应。不要编造信息。"),
            ("user", "{input}"),
        ])
        
        prompt_value = direct_prompt.invoke({"input": current_query})
        response = await self.chat_model.ainvoke(prompt_value)
        
        return {"messages": [response]}
    
    async def _evaluate_retrieval_node(self, state: RagState) -> dict:
        """评估节点：判断检索结果的质量。
        
        使用简单的启发式规则评估：
        - 如果 context 为空或太短 → 质量差
        - 如果包含"无相关参考资料" → 质量差
        - 否则 → 质量好
        
        Args:
            state: 当前图状态（含 context）
            
        Returns:
            {"retrieval_quality": 0.0-1.0}
        """
        context = state.get("context", "")
        
        # 质量评分逻辑
        if not context or context == "无相关参考资料":
            quality = 0.0
        elif len(context) < 50:
            quality = 0.3
        elif len(context) < 200:
            quality = 0.6
        else:
            quality = 0.9
        
        return {"retrieval_quality": quality}
    
    async def _rewrite_query_node(self, state: RagState) -> dict:
        """改写节点：当检索质量差时，重新改写查询并重试。
        
        Args:
            state: 当前图状态（含 messages、retry_count）
            
        Returns:
            {"messages": [HumanMessage]} — 用改写后的查询替换原查询
        """
        messages = state.get("messages", [])
        retry_count = state.get("retry_count", 0)
        
        if not messages:
            return {"messages": [], "retry_count": retry_count + 1}
        
        original_query = messages[-1].content if hasattr(messages[-1], "content") else str(messages[-1])
        history = list(messages[:-1]) if len(messages) > 1 else None
        
        # 强制改写上一次的查询
        rewritten_query = await self.query_rewriter.arewrite(
            original_query, 
            history,
            force=True  # 强制改写
        )
        
        # 用改写后的查询替换最后一条消息
        new_messages = list(messages[:-1]) + [HumanMessage(content=rewritten_query)]
        
        return {
            "messages": new_messages,
            "retry_count": retry_count + 1
        }

    async def _retrieve_node(self, state: RagState) -> dict:
        """检索节点：查询改写 → 混合检索 → 重排序 → Parent-Child 展开。

        从 state.messages 中提取最新用户消息作为查询，
        使用历史消息进行指代消解和查询扩展。

        Args:
            state: 当前图状态（含 messages）

        Returns:
            {"context": "拼接后的参考文本", "retry_count": int}
        """
        messages = state.get("messages", [])
        retry_count = state.get("retry_count", 0)
        
        if not messages:
            return {"context": "无相关参考资料", "retry_count": retry_count}

        # 最新消息即为用户当前查询
        query = messages[-1].content if hasattr(messages[-1], "content") else str(messages[-1])

        # 历史消息（不含当前查询）用于指代消解
        history = list(messages[:-1]) if len(messages) > 1 else None

        # Step 1: 查询改写（异步 LLM 调用）
        rewritten_query = await self.query_rewriter.arewrite(query, history)

        # Step 2: 混合检索（CPU-bound → asyncio.to_thread）
        docs = await asyncio.to_thread(
            self.hybrid_retriever.retrieve, rewritten_query
        )

        # Step 3: 重排序（异步 API 调用）
        if docs:
            docs = await self.reranker.arerank(rewritten_query, docs)

        if not docs:
            return {"context": "无相关参考资料"}

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

        context = "\n\n---\n\n".join(parts)
        return {"context": context, "retry_count": retry_count}

    async def _generate_node(self, state: RagState) -> dict:
        """生成节点：使用提示词模板 + LLM 生成回答。

        从 state 中提取 context 和历史消息，
        格式化提示词后调用 ChatTongyi 生成回答。

        Args:
            state: 当前图状态（含 messages、context）

        Returns:
            {"messages": [AIMessage]} — add_messages reducer 自动追加到历史
        """
        messages = state.get("messages", [])
        context = state.get("context", "无相关参考资料")

        # 当前查询 = 最后一条消息
        current_query = messages[-1].content if messages else ""

        # 历史 = 除当前查询外的所有消息
        history = list(messages[:-1]) if len(messages) > 1 else []

        # 格式化提示词
        prompt_value = self.prompt_template.invoke({
            "context": context,
            "history": history,
            "input": current_query,
        })

        # 调用 LLM
        response = await self.chat_model.ainvoke(prompt_value)

        return {"messages": [response]}

    # ================================================================
    # 异步接口（FastAPI / aiohttp 等异步框架）
    # ================================================================

    async def ainvoke(self, input_data: dict, session_config: dict) -> str:
        """异步调用（非流式），返回完整回答。

        Args:
            input_data: {"input": "用户查询"}
            session_config: {"configurable": {"session_id": "..."}}

        Returns:
            完整回答字符串
        """
        graph = await self._ensure_graph()
        query = input_data["input"]
        session_id = session_config["configurable"]["session_id"]



        config = {"configurable": {"thread_id": session_id}}

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config,
        )

        # 提取最后一条 AI 消息的内容
        all_messages = result.get("messages", [])
        if all_messages and isinstance(all_messages[-1], AIMessage):
            return all_messages[-1].content
        return ""

    async def astream(self, input_data: dict, session_config: dict) -> AsyncIterator[str]:
        """异步流式调用，逐个 token 产出。

        使用 LangGraph 的 stream_mode="messages" 实现 token 级别流式输出。
        graph 内部自动将 LLM 生成的 token 作为 AIMessageChunk 流式产出。

        Args:
            input_data: {"input": "用户查询"}
            session_config: {"configurable": {"session_id": "..."}}

        Yields:
            生成的 token 字符串
        """
        graph = await self._ensure_graph()
        query = input_data["input"]
        session_id = session_config["configurable"]["session_id"]

        config = {"configurable": {"thread_id": session_id}}

        async for msg, metadata in graph.astream(
            {"messages": [HumanMessage(content=query)]},
            config,
            stream_mode="messages",
        ):
            # 仅产出 AI 消息的 token 内容
            if isinstance(msg, AIMessageChunk) and msg.content:
                yield msg.content

    # ================================================================
    # 资源管理
    # ================================================================

    async def close(self):
        """关闭 checkpointer 的数据库连接。"""
        if self._checkpointer_conn is not None:
            await self._checkpointer_conn.close()
            self._checkpointer_conn = None
            self._checkpointer = None
            self._graph = None

    def __del__(self):
        """析构时尝试关闭连接（best-effort）。"""
        if self._checkpointer_conn is not None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._checkpointer_conn.close())
                else:
                    asyncio.run(self._checkpointer_conn.close())
            except Exception:
                pass  # 析构时忽略所有错误


# ================================================================
# 测试入口
# ================================================================

async def _test_async():
    """异步测试函数。"""
    svc = AsyncRagService()
    session_config = config.build_session_config("test_langgraph_user")
    print("=== LangGraph RAG 测试 ===")
    async for chunk in svc.astream(
        {"input": "针织毛衣如何保养？"}, session_config
    ):
        print(chunk, end="", flush=True)
    print()
    await svc.close()


if __name__ == "__main__":
    asyncio.run(_test_async())
