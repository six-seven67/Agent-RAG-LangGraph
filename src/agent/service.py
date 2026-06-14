"""
知识库文档问答 Agent 服务 — 基于 LangGraph 自定义 StateGraph

v3.3.0: 节点提取到 nodes.py + 幻觉校验 + Token 双阈值压缩 + 会话结束总结

架构:
  StateGraph(AgentState)  — 6 节点
    ├── classify_intent 节点: 规则匹配快速路由（闲聊/结束/继续）
    ├── summarize 节点: 轮次 + Token 双阈值触发对话压缩
    ├── agent 节点: ReAct 循环（LLM + bind_tools ⇄ tools）
    ├── tools 节点: ToolNode 执行工具调用
    ├── hallucination_check 节点: 验证回答是否基于文档内容
    └── session_end_summary 节点: 会话结束全局总结

流式输出:
  使用 graph.astream(stream_mode="messages") 捕获：
  - AIMessageChunk → token 事件（逐字输出）
  - AIMessage(tool_calls) → tool_start 事件
  - ToolMessage → tool_end 事件
  - [HALLUCINATION_FAIL] → hallucination 事件

向后兼容:
  设置 AGENT_BACKEND=legacy 可切回 create_agent 模式。

Usage:
    svc = AgentService(user_id=1)
    async for event in svc.astream({"input": "..."}, config):
        print(event)  # {"type": "token", "data": "..."} | {"type": "tool_start", ...}
"""

import asyncio
import logging
import os
import time
from typing import AsyncIterator, Literal

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from langchain_core.messages import (
    HumanMessage, AIMessage, ToolMessage, SystemMessage
)
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models.tongyi import ChatTongyi

from src.retrieval import VectorStoreService
from src.retrieval import RerankerService
from src.retrieval import BM25Retriever
from src.retrieval import HybridRetriever
from src.rag.rewriter import QueryRewriter
from src.agent.tools import (
    make_search_knowledge_base,
    make_web_search,
)
from src.agent.state import AgentState
from src.agent.prompts import AGENT_SYSTEM_PROMPT
from src.agent.formatter import format_answer_output
from src.agent.nodes import (
    classify_intent_wrapper,
    summarize_node,
    agent_node,
    tools_node,
    session_end_summary_node,
    hallucination_check_node,
)
from src.agent.streaming import (
    init_event_tracking, classify_chunk
)
import src.config as config

# ---- 日志 ----
logger = logging.getLogger("AgentService")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(_handler)

# ---- 持久化根目录 ----
STORAGE_ROOT = config.chat_history_path


class AgentService:
    """知识库文档问答 Agent 服务（混合架构 StateGraph）。

    v3.3.0 架构（6 节点）:
      classify_intent → [direct_chat | end_session | summarize]
      summarize → agent ⇄ tools（ReAct 循环）
      agent → hallucination_check（文档问答完成时校验）
      hallucination_check → agent（未通过）| END（通过）
      session_end_summary → END

    特性:
    - 规则匹配快速路由：拦截闲聊 / 结束会话，减少延迟
    - ReAct 循环：LLM 自主决策是否检索知识库
    - 幻觉校验：回答完成后自动检查是否严格基于文档内容
    - 双阈值压缩：轮次 + Token 双重触发对话压缩
    - 会话结束总结：用户结束时生成全局摘要

    每个用户使用独立的 SQLite 数据库文件 + Chroma collection，实现用户隔离。
    """

    def __init__(self, user_id: int = None):
        """初始化 Agent 服务（轻量级，检索组件延迟加载）。
        
        设计原因：
        - 采用延迟加载模式，避免不必要的资源消耗
        - 用户ID用于实现数据隔离和个性化服务
        - 初始化核心LLM模型，其他组件按需加载以优化启动性能
        """
        self.user_id = user_id
        logger.info("初始化 AgentService（user_id=%s, backend=%s）", user_id, config.agent_backend)

        # ---- 用户隔离 ----
        # 为每个用户创建独立的集合名称，确保知识库数据隔离
        self._collection_name = None
        if user_id is not None:
            self._collection_name = config.get_user_collection_name(user_id)

        # ---- LLM（立即初始化）----
        # 聊天模型是核心组件，需要立即初始化以支持基本对话功能
        self.chat_model = ChatTongyi(
            model=config.chat_model_name,
            streaming=True,
        )

        # ---- 延迟加载的组件 ----
        # 以下组件在首次使用时才初始化，减少内存占用和启动时间
        self._summary_model = None  # 摘要生成专用模型
        self._vector_service = None  # 向量存储服务
        self._hybrid_retriever = None  # 混合检索器（向量+BM25）
        self._reranker = None  # 重排序服务
        self._query_rewriter = None  # 查询重写器
        self._search_tool = None  # 搜索工具
        self._tools = None  # 所有可用工具列表
        self._web_search_tool = make_web_search()  # 网络搜索工具

        # ---- Graph（延迟编译）----
        # LangGraph图结构和相关组件，首次请求时才构建
        self._graph = None
        self._tool_node = None
        self._model_with_tools = None
        self._checkpointer_conn = None
        self._checkpointer = None

        # ---- 摘要轮次追踪 ----
        # 跟踪上次执行摘要的轮次，避免频繁生成摘要造成资源浪费
        self._last_summary_rounds = 0

        # ---- 事件追踪（每次请求重置）----
        # 用于流式输出时跟踪工具调用状态
        self._seen_tool_starts = set()
        self._tool_call_id_to_name = {}

        # ---- 用户隔离：SQLite checkpoint 路径 ----
        # 为每个用户创建独立的检查点数据库，保存对话历史和状态
        db_name = (
            f"checkpoints_agent_user_{user_id}.db"
            if user_id is not None
            else "checkpoints_agent_default.db"
        )
        self._checkpoint_db_path = os.path.join(STORAGE_ROOT, db_name)
        os.makedirs(os.path.dirname(self._checkpoint_db_path), exist_ok=True)

    # ================================================================
    # Lazy Properties
    # ================================================================

    @property
    def summary_model(self):
        """获取摘要模型，延迟初始化。
        
        设计原因：
        - 摘要生成不需要实时进行，仅在达到特定轮次或会话结束时触发
        - 使用专门的温度参数(temperature=0.0)确保摘要的一致性和准确性
        """
        if self._summary_model is None:
            self._summary_model = ChatTongyi(
                model=config.chat_model_name, temperature=0.0)
        return self._summary_model

    @property
    def vector_service(self):
        """获取向量存储服务，延迟初始化。
        
        设计原因：
        - 向量存储只在需要进行语义检索时才加载
        - 使用用户特定的collection_name实现数据隔离
        """
        if self._vector_service is None:
            logger.debug("延迟初始化 VectorStoreService（collection=%s）", self._collection_name)
            self._vector_service = VectorStoreService(
                embedding=DashScopeEmbeddings(model=config.embedding_model_name),
                collection_name=self._collection_name,
            )
        return self._vector_service

    @property
    def hybrid_retriever(self):
        """获取混合检索器，延迟初始化。
        
        设计原因：
        - 结合向量检索和BM25关键词检索的优势，提高检索准确率
        - 只有在真正需要检索时才构建检索器，节省资源
        """
        if self._hybrid_retriever is None:
            logger.debug("延迟初始化 HybridRetriever + BM25")
            vector_retriever = self.vector_service.get_retriever()
            all_docs = self.vector_service.get_all_documents()
            bm25_retriever = BM25Retriever(all_docs)
            self._hybrid_retriever = HybridRetriever(vector_retriever, bm25_retriever)
        return self._hybrid_retriever

    @property
    def reranker(self):
        """获取重排序服务，延迟初始化。
        
        设计原因：
        - 对初步检索结果进行精排，提高最终返回文档的相关性
        - 作为可选优化步骤，按需加载
        """
        if self._reranker is None:
            self._reranker = RerankerService()
        return self._reranker

    @property
    def query_rewriter(self):
        """获取查询重写器，延迟初始化。
        
        设计原因：
        - 将用户原始查询转换为更适合检索的形式
        - 改善检索效果，特别是在处理复杂或多义词查询时
        """
        if self._query_rewriter is None:
            self._query_rewriter = QueryRewriter()
        return self._query_rewriter

    @property
    def tools(self):
        """获取所有可用工具列表，延迟初始化。

        设计原因：
        - 整合所有可用的工具函数供Agent调用
        - 包括知识库搜索和网络搜索
        - 首次访问时才完整构建，避免不必要的初始化开销
        """
        if self._tools is None:
            if self._search_tool is None:
                logger.info("首次加载检索组件（embedding/BM25/Chroma/Reranker）")
                self._search_tool = make_search_knowledge_base(
                    self.query_rewriter, self.hybrid_retriever, self.reranker)
            self._tools = [
                self._search_tool,
                self._web_search_tool,
            ]
        return self._tools

    # ================================================================
    # Graph 构建
    # ================================================================

    def _build_graph(self):
        """构建自定义 StateGraph（v3.3.0 混合架构 + 幻觉校验）。"""
        if config.agent_backend == "legacy":
            logger.warning("使用 LEGACY 后端（create_agent）")
            return self._build_legacy_graph()

        logger.info("构建 Custom StateGraph（v3.3.0 节点=%d + 幻觉校验）", 6)
        graph = StateGraph(AgentState)

        # 注册节点
        graph.add_node("classify_intent", self._classify_intent_node)
        graph.add_node("summarize", self._summarize_node)
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self._lazy_tools_node)
        graph.add_node("session_end_summary", self._session_end_summary_node)
        graph.add_node("hallucination_check", self._hallucination_check_node)
        logger.debug("已注册 6 个节点: classify_intent, summarize, agent, tools, "
                     "session_end_summary, hallucination_check")

        # 边连接
        graph.add_edge(START, "classify_intent")
        graph.add_conditional_edges(
            "classify_intent", self._route_intent,
            {"direct_chat": END, "end_session": "session_end_summary", "continue": "summarize"},
        )
        graph.add_edge("summarize", "agent")
        graph.add_conditional_edges(
            "agent", self._should_continue,
            {
                "tools": "tools",
                "hallucination_check": "hallucination_check",
                "__end__": END,
            },
        )
        graph.add_edge("tools", "agent")
        graph.add_conditional_edges(
            "hallucination_check", self._should_recheck,
            {"agent": "agent", "__end__": END},
        )
        graph.add_edge("session_end_summary", END)

        return graph.compile(checkpointer=self._checkpointer)

    def _build_legacy_graph(self):
        """Legacy 模式：使用 create_agent（向后兼容）。"""
        from langchain.agents import create_agent
        return create_agent(
            model=self.chat_model,
            tools=self.tools,
            checkpointer=self._checkpointer,
            system_prompt=AGENT_SYSTEM_PROMPT,
        )

    # ================================================================
    # 路由函数
    # ================================================================

    @staticmethod
    def _route_intent(state: AgentState) -> Literal["direct_chat", "end_session", "continue"]:
        from src.agent.classifier import route_intent
        return route_intent(state, AgentService._count_rounds)

    @staticmethod
    def _should_continue(state: AgentState) -> Literal["tools", "hallucination_check", "__end__"]:
        """agent 节点后路由。

        - tool_calls → tools 节点执行工具
        - 无 tool_calls + 有检索历史 → hallucination_check 校验
        - 无 tool_calls + 无检索历史 → __end__ 结束（闲聊/追问）
        """
        messages = state.get("messages", [])
        if not messages:
            logger.debug("ReAct 路由: __end__（无消息）")
            return "__end__"
        last_msg = messages[-1]
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            tool_names = [tc.get("name", "?") for tc in last_msg.tool_calls]
            logger.info("ReAct 路由: tools → 调用 %s", tool_names)
            return "tools"

        # 无 tool_calls → 检查是否发生过检索
        has_retrieval = any(isinstance(m, ToolMessage) for m in messages)
        if has_retrieval:
            logger.debug("ReAct 路由: hallucination_check（回答完成，发生过检索）")
            return "hallucination_check"

        logger.debug("ReAct 路由: __end__（无检索对话）")
        return "__end__"

    @staticmethod
    def _should_recheck(state: AgentState) -> Literal["agent", "__end__"]:
        """幻觉校验后路由。

        - 已达最大重试次数 → __end__ 强行结束
        - 最后消息含 [HALLUCINATION_FAIL] 标记 → agent 重新生成
        - 否则 → __end__ 正常结束
        """
        if state.get("hallucination_retry_count", 0) > 1:
            logger.debug("幻觉路由: __end__（已达最大重试）")
            return "__end__"
        messages = state.get("messages", [])
        if messages:
            last_msg = messages[-1]
            if isinstance(last_msg, AIMessage):
                pass  # not a fail marker, continue to check
            # 查找最近的 [HALLUCINATION_FAIL] 标记（作为 SystemMessage 被注入）
            for msg in reversed(messages):
                if isinstance(msg, SystemMessage) and "[系统指令] 上一轮回答存在事实问题" in str(msg.content):
                    logger.info("幻觉路由: agent（重新生成）")
                    return "agent"
        logger.debug("幻觉路由: __end__（校验通过）")
        return "__end__"

    @staticmethod
    def _count_rounds(messages: list) -> int:
        return sum(1 for m in messages if isinstance(m, HumanMessage))

    # ================================================================
    # 节点: classify_intent（委托 nodes.py）
    # ================================================================

    async def _classify_intent_node(self, state: AgentState) -> dict:
        return await classify_intent_wrapper(self, state)

    # ================================================================
    # 节点: summarize（委托 nodes.py）
    # ================================================================

    async def _summarize_node(self, state: AgentState) -> dict:
        return await summarize_node(self, state)

    # ================================================================
    # 节点: agent（委托 nodes.py）
    # ================================================================

    async def _agent_node(self, state: AgentState) -> dict:
        return await agent_node(self, state)

    # ================================================================
    # 节点: tools（委托 nodes.py）
    # ================================================================

    async def _lazy_tools_node(self, state: AgentState) -> dict:
        return await tools_node(self, state)

    # ================================================================
    # 节点: session_end_summary（委托 nodes.py）
    # ================================================================

    async def _session_end_summary_node(self, state: AgentState) -> dict:
        return await session_end_summary_node(self, state)

    # ================================================================
    # 节点: hallucination_check（委托 nodes.py，v3.3.0 新增）
    # ================================================================

    async def _hallucination_check_node(self, state: AgentState) -> dict:
        return await hallucination_check_node(self, state)

    # ================================================================
    # 延迟初始化 Graph
    # ================================================================

    async def _ensure_graph(self):
        if self._graph is not None:
            return self._graph
        t0 = time.monotonic()
        import aiosqlite
        logger.info("首次初始化 Graph（checkpoint_db=%s）", self._checkpoint_db_path)
        self._checkpointer_conn = await aiosqlite.connect(self._checkpoint_db_path)
        self._checkpointer = AsyncSqliteSaver(self._checkpointer_conn)
        self._graph = self._build_graph()
        elapsed = time.monotonic() - t0
        logger.info("Graph 编译完成（耗时 %.2fs）", elapsed)
        return self._graph

    # ================================================================
    # 公共 API — ainvoke（非流式）
    # ================================================================

    async def ainvoke(self, input_data: dict, session_config: dict) -> str:
        t0 = time.monotonic()
        graph = await self._ensure_graph()
        query = input_data["input"]
        session_id = session_config["configurable"]["session_id"]

        init_event_tracking(self)
        logger.info("ainvoke: 收到查询（session=%s, query=%s）", session_id, query[:100])
        config_lg = {"configurable": {"thread_id": session_id}}

        try:
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content=query)]}, config_lg)
            elapsed = time.monotonic() - t0

            all_messages = result.get("messages", [])
            answer = ""
            for msg in reversed(all_messages):
                if isinstance(msg, AIMessage) and msg.content:
                    answer = msg.content
                    break

            answer = format_answer_output(answer)
            logger.info("ainvoke: 完成（耗时 %.2fs, 回答长度=%d, 总消息数=%d）",
                         elapsed, len(answer), len(all_messages))
            return answer
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error("ainvoke: 失败（耗时 %.2fs, session=%s）: %s",
                         elapsed, session_id, e, exc_info=True)
            raise

    # ================================================================
    # 公共 API — astream（流式）
    # ================================================================

    async def astream(
        self, input_data: dict, session_config: dict
    ) -> AsyncIterator[dict]:
        t0 = time.monotonic()
        graph = await self._ensure_graph()
        query = input_data["input"]
        session_id = session_config["configurable"]["session_id"]

        init_event_tracking(self)
        logger.info("astream: 收到流式查询（session=%s, query=%s）", session_id, query[:100])
        config_lg = {"configurable": {"thread_id": session_id}}

        event_count = 0
        tool_count = 0
        token_count = 0
        try:
            async for msg, metadata in graph.astream(
                {"messages": [HumanMessage(content=query)]},
                config_lg, stream_mode="messages",
            ):
                event = classify_chunk(msg, metadata, self)
                event_count += 1
                if event["type"] == "token":
                    token_count += len(event.get("data", ""))
                elif event["type"] == "tool_start":
                    tool_count += 1
                if event["type"] == "thinking" and not event["data"]:
                    continue
                yield event

            elapsed = time.monotonic() - t0
            logger.info("astream: 完成（耗时 %.2fs, 事件=%d, tokens=%d, 工具=%d, session=%s）",
                         elapsed, event_count, token_count, tool_count, session_id)
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error("astream: 失败（耗时 %.2fs, 事件=%d, session=%s）: %s",
                         elapsed, event_count, session_id, e, exc_info=True)
            raise

    # ================================================================
    # 公共 API — astream_text（纯文本流）
    # ================================================================

    async def astream_text(
        self, input_data: dict, session_config: dict
    ) -> AsyncIterator[str]:
        async for event in self.astream(input_data, session_config):
            if event["type"] == "token":
                yield event["data"]
            elif event["type"] == "tool_start":
                tools_info = event.get("data", {}).get("tools", [])
                tool_names = [t.get("name", "") for t in tools_info]
                yield f"\n🔍 正在调用工具: {', '.join(tool_names)}...\n"
            elif event["type"] == "tool_end":
                yield "\n✅ 工具执行完成\n"
            elif event["type"] == "summarize":
                yield "\n📝 对话历史已自动总结...\n"
            elif event["type"] == "session_end":
                yield "\n📋 正在生成会话总结...\n"
            elif event["type"] == "thinking":
                pass

    # ================================================================
    # 资源管理
    # ================================================================

    async def close(self):
        if self._checkpointer_conn is not None:
            logger.info("关闭 AgentService（user_id=%s）", self.user_id)
            await self._checkpointer_conn.close()
            self._checkpointer_conn = None
            self._checkpointer = None
            self._graph = None
        else:
            logger.debug("close: 无需清理（连接未初始化）")

    def __del__(self):
        if self._checkpointer_conn is not None:
            logger.debug("__del__: 尝试清理连接（user_id=%s）", self.user_id)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._checkpointer_conn.close())
                else:
                    asyncio.run(self._checkpointer_conn.close())
            except Exception as e:
                logger.warning("__del__: 清理失败: %s", e)


async def _test_agent():
    """异步测试 Agent 服务。"""
    svc = AgentService()
    session_config = config.build_session_config("test_agent_user")
    print("=== 知识库文档问答 Agent 测试 (v3.3.0) ===")
    async for event in svc.astream(
        {"input": "针织毛衣如何保养？"}, session_config
    ):
        print(f"[{event['type']}] {event['data']}")
    print()
    await svc.close()


if __name__ == "__main__":
    asyncio.run(_test_agent())
