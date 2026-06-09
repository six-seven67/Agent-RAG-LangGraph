"""
Agent 智能客服服务 — 基于 LangGraph 自定义 StateGraph

v3.2.0: 混合架构 — 规则路由 + ReAct 循环 + 会话结束总结

架构:
  StateGraph(AgentState)
    ├── classify_intent 节点: 规则匹配快速路由（FAQ/转人工/结束/继续）
    ├── summarize 节点: 轮次触发对话压缩
    ├── agent 节点: ReAct 循环（LLM + bind_tools ⇄ tools）
    ├── tools 节点: ToolNode 执行工具调用
    └── session_end_summary 节点: 会话结束全局总结

流式输出:
  使用 graph.astream(stream_mode="messages") 捕获：
  - AIMessageChunk → token 事件（逐字输出）
  - AIMessage(tool_calls) → tool_start 事件
  - ToolMessage → tool_end 事件

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
from langgraph.prebuilt import ToolNode
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
    escalate_to_human,
    lookup_faq,
    make_web_search,
)
from src.agent.state import AgentState
from src.agent.prompts import (
    AGENT_SYSTEM_PROMPT, SUMMARIZE_PROMPT, SESSION_END_SUMMARY_PROMPT
)
from src.agent.formatter import format_answer_output
from src.agent.classifier import classify_intent_node
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
    """Agent 智能客服服务（混合架构 StateGraph）。

    v3.2.0 架构:
      classify_intent → [faq_direct | end_session | summarize]
      summarize → agent ⇄ tools（ReAct 循环）
      session_end_summary → END

    特性:
    - 规则匹配快速路由：拦截 FAQ / 转人工 / 结束会话，减少延迟
    - ReAct 循环：保持多工具链式调用的灵活性
    - 轮次触发总结：按对话轮数自动压缩历史
    - 会话结束总结：用户结束时生成全局摘要

    每个用户使用独立的 SQLite 数据库文件 + Chroma collection，实现用户隔离。
    """

    def __init__(self, user_id: int = None):
        """初始化 Agent 服务（轻量级，检索组件延迟加载）。"""
        self.user_id = user_id
        logger.info("初始化 AgentService（user_id=%s, backend=%s）", user_id, config.agent_backend)

        # ---- 用户隔离 ----
        self._collection_name = None
        if user_id is not None:
            self._collection_name = config.get_user_collection_name(user_id)

        # ---- LLM（立即初始化）----
        self.chat_model = ChatTongyi(
            model=config.chat_model_name,
            streaming=True,
        )

        # ---- 延迟加载的组件 ----
        self._summary_model = None
        self._vector_service = None
        self._hybrid_retriever = None
        self._reranker = None
        self._query_rewriter = None
        self._search_tool = None
        self._tools = None
        self._web_search_tool = make_web_search()

        # ---- Graph（延迟编译）----
        self._graph = None
        self._tool_node = None
        self._model_with_tools = None
        self._checkpointer_conn = None
        self._checkpointer = None

        # ---- 摘要轮次追踪 ----
        self._last_summary_rounds = 0

        # ---- 事件追踪（每次请求重置）----
        self._seen_tool_starts = set()
        self._tool_call_id_to_name = {}

        # ---- 用户隔离：SQLite checkpoint 路径 ----
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
        if self._summary_model is None:
            self._summary_model = ChatTongyi(
                model=config.chat_model_name, temperature=0.0)
        return self._summary_model

    @property
    def vector_service(self):
        if self._vector_service is None:
            logger.debug("延迟初始化 VectorStoreService（collection=%s）", self._collection_name)
            self._vector_service = VectorStoreService(
                embedding=DashScopeEmbeddings(model=config.embedding_model_name),
                collection_name=self._collection_name,
            )
        return self._vector_service

    @property
    def hybrid_retriever(self):
        if self._hybrid_retriever is None:
            logger.debug("延迟初始化 HybridRetriever + BM25")
            vector_retriever = self.vector_service.get_retriever()
            all_docs = self.vector_service.get_all_documents()
            bm25_retriever = BM25Retriever(all_docs)
            self._hybrid_retriever = HybridRetriever(vector_retriever, bm25_retriever)
        return self._hybrid_retriever

    @property
    def reranker(self):
        if self._reranker is None:
            self._reranker = RerankerService()
        return self._reranker

    @property
    def query_rewriter(self):
        if self._query_rewriter is None:
            self._query_rewriter = QueryRewriter()
        return self._query_rewriter

    @property
    def tools(self):
        if self._tools is None:
            if self._search_tool is None:
                logger.info("首次加载检索组件（embedding/BM25/Chroma/Reranker）")
                self._search_tool = make_search_knowledge_base(
                    self.query_rewriter, self.hybrid_retriever, self.reranker)
            self._tools = [
                self._search_tool,
                self._web_search_tool,
                lookup_faq,
                escalate_to_human,
            ]
        return self._tools

    # ================================================================
    # Graph 构建
    # ================================================================

    def _build_graph(self):
        """构建自定义 StateGraph（v3.2.0 混合架构）。"""
        if config.agent_backend == "legacy":
            logger.warning("使用 LEGACY 后端（create_agent）")
            return self._build_legacy_graph()

        logger.info("构建 Custom StateGraph（v3.2.0 混合架构）")
        graph = StateGraph(AgentState)

        # 注册节点
        graph.add_node("classify_intent", self._classify_intent_node)
        graph.add_node("summarize", self._summarize_node)
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self._lazy_tools_node)
        graph.add_node("session_end_summary", self._session_end_summary_node)
        logger.debug("已注册 5 个节点: classify_intent, summarize, agent, tools, session_end_summary")

        # 边连接
        graph.add_edge(START, "classify_intent")
        graph.add_conditional_edges(
            "classify_intent", self._route_intent,
            {"faq_direct": END, "end_session": "session_end_summary", "continue": "summarize"},
        )
        graph.add_edge("summarize", "agent")
        graph.add_conditional_edges(
            "agent", self._should_continue,
            {"tools": "tools", "__end__": END},
        )
        graph.add_edge("tools", "agent")
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
    def _route_intent(state: AgentState) -> Literal["faq_direct", "end_session", "continue"]:
        from src.agent.classifier import route_intent
        return route_intent(state, AgentService._count_rounds)

    @staticmethod
    def _should_continue(state: AgentState) -> Literal["tools", "__end__"]:
        messages = state.get("messages", [])
        if not messages:
            logger.debug("ReAct 路由: __end__（无消息）")
            return "__end__"
        last_msg = messages[-1]
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            tool_names = [tc.get("name", "?") for tc in last_msg.tool_calls]
            logger.info("ReAct 路由: tools → 调用 %s", tool_names)
            return "tools"
        logger.debug("ReAct 路由: __end__（LLM 直接回答，无 tool_calls）")
        return "__end__"

    @staticmethod
    def _count_rounds(messages: list) -> int:
        return sum(1 for m in messages if isinstance(m, HumanMessage))

    # ================================================================
    # 节点: classify_intent
    # ================================================================

    async def _classify_intent_node(self, state: AgentState) -> dict:
        return await classify_intent_node(state, self._count_rounds)

    # ================================================================
    # 节点: summarize
    # ================================================================

    async def _summarize_node(self, state: AgentState) -> dict:
        t0 = time.monotonic()
        messages = state.get("messages", [])
        rounds = self._count_rounds(messages)
        threshold = config.agent_summary_trigger_rounds
        keep_recent = config.agent_summary_keep_recent
        max_chars = config.agent_summary_max_chars

        # 短路检查
        if rounds < threshold:
            logger.debug("summarize: 短路（轮次=%d < 阈值=%d）", rounds, threshold)
            return {"summary_updated": False}

        if rounds - self._last_summary_rounds < config.agent_summary_min_interval_rounds:
            logger.debug("summarize: 短路（距上次总结仅 %d 轮 < 最小间隔 %d）",
                         rounds - self._last_summary_rounds, config.agent_summary_min_interval_rounds)
            return {"summary_updated": False}

        if len(messages) <= keep_recent:
            logger.debug("summarize: 短路（消息数=%d ≤ 保留数=%d）", len(messages), keep_recent)
            return {"summary_updated": False}

        old_messages = list(messages[:-keep_recent])
        recent_messages = list(messages[-keep_recent:])

        logger.info("summarize: 触发总结（轮次=%d, 旧消息=%d条, 保留=%d条）",
                     rounds, len(old_messages), len(recent_messages))

        # 格式化旧消息
        old_text_parts = []
        for msg in old_messages:
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            content = msg.content if hasattr(msg, "content") else str(msg)
            if content and len(content) > 300:
                content = content[:300] + "..."
            old_text_parts.append(f"[{role}]: {content}")
        old_text = "\n".join(old_text_parts)

        # 增量合并指令
        existing_summary = state.get("summary", "")
        existing_instruction = (
            f"当前已有摘要: 「{existing_summary}」\n"
            "请将其与以下新对话合并，更新为新的运行摘要。"
        ) if existing_summary else "这是首次生成摘要。"

        # 调用 LLM
        try:
            prompt = SUMMARIZE_PROMPT.format(
                existing_summary_instruction=existing_instruction,
                max_chars=max_chars,
                old_messages_text=old_text,
            )
            logger.debug("summarize: 调用摘要 LLM（prompt 长度=%d）", len(prompt))
            response = await self.summary_model.ainvoke(prompt)
            new_summary = response.content if hasattr(response, "content") else str(response)
            new_summary = new_summary.strip()
            if len(new_summary) > max_chars * 2:
                new_summary = new_summary[:max_chars * 2]
            elapsed = time.monotonic() - t0
            logger.info("summarize: 完成（%d字, 耗时 %.2fs）", len(new_summary), elapsed)
        except Exception as e:
            logger.error("summarize: LLM 调用失败，跳过总结: %s", e, exc_info=True)
            return {"summary_updated": False}

        self._last_summary_rounds = rounds
        summary_msg = SystemMessage(
            content=f"[对话历史摘要]\n{new_summary}\n---\n以下是最近的对话："
        )
        return {
            "messages": [summary_msg] + recent_messages,
            "summary": new_summary,
            "summary_updated": True,
        }

    # ================================================================
    # 节点: agent
    # ================================================================

    async def _agent_node(self, state: AgentState) -> dict:
        t0 = time.monotonic()
        messages = state.get("messages", [])
        summary = state.get("summary", "")
        rounds = self._count_rounds(messages)

        system_content = AGENT_SYSTEM_PROMPT.format(
            summary=summary if summary else "（暂无对话摘要）"
        )
        full_messages = [SystemMessage(content=system_content)] + list(messages)

        if self._model_with_tools is None:
            self._model_with_tools = self.chat_model.bind_tools(self.tools)
        model_with_tools = self._model_with_tools
        logger.debug("agent: 调用 LLM（消息数=%d, 轮次=%d, 工具数=%d）",
                      len(full_messages), rounds, len(self.tools))

        try:
            response = await model_with_tools.ainvoke(full_messages)
            elapsed = time.monotonic() - t0
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_info = [(tc.get("name", "?"), str(tc.get("args", {}))[:80])
                             for tc in response.tool_calls]
                logger.info("agent: LLM 决定调用工具（耗时 %.2fs）%s", elapsed, tool_info)
            else:
                preview = (response.content[:80] + "...") if hasattr(response, "content") and len(response.content or "") > 80 else (response.content or "")
                logger.info("agent: LLM 直接回答（耗时 %.2fs）: %s", elapsed, preview)
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error("agent: LLM 调用失败（耗时 %.2fs）: %s", elapsed, e, exc_info=True)
            return {
                "messages": [AIMessage(content="抱歉，我暂时无法处理您的请求，请稍后再试。如需紧急帮助，可转人工客服。")]
            }
        return {"messages": [response]}

    # ================================================================
    # 节点: tools（懒加载 ToolNode）
    # ================================================================

    async def _lazy_tools_node(self, state: AgentState) -> dict:
        if self._tool_node is None:
            logger.info("首次创建 ToolNode（触发检索组件懒加载）")
            self._tool_node = ToolNode(self.tools)
        return await self._tool_node.ainvoke(state)

    # ================================================================
    # 节点: session_end_summary
    # ================================================================

    async def _session_end_summary_node(self, state: AgentState) -> dict:
        t0 = time.monotonic()
        messages = state.get("messages", [])
        total_rounds = self._count_rounds(messages)

        tool_names = set()
        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_names.add(getattr(msg, "name", "unknown"))

        logger.info("session_end_summary: 开始生成全局总结（轮次=%d, 消息数=%d, 工具=%s）",
                     total_rounds, len(messages), list(tool_names))

        # 格式化对话文本
        conversation_parts = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                role = "用户"
            elif isinstance(msg, AIMessage):
                role = "助手"
            elif isinstance(msg, ToolMessage):
                role = "系统(工具)"
            elif isinstance(msg, SystemMessage):
                if "[对话历史摘要]" in str(msg.content):
                    continue
                role = "系统"
            else:
                continue
            content = msg.content if hasattr(msg, "content") else str(msg)
            if content and len(content) > 500:
                content = content[:500] + "..."
            conversation_parts.append(f"[{role}]: {content}")

        conversation_text = "\n".join(conversation_parts)

        # 调用 LLM
        try:
            prompt = SESSION_END_SUMMARY_PROMPT.format(conversation_text=conversation_text)
            logger.debug("session_end_summary: 调用 LLM（prompt 长度=%d）", len(prompt))
            response = await self.summary_model.ainvoke(prompt)
            summary_text = response.content if hasattr(response, "content") else str(response)
            summary_text = summary_text.strip()
            elapsed = time.monotonic() - t0
            logger.info("session_end_summary: 完成（%d字, 耗时 %.2fs）", len(summary_text), elapsed)
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error("session_end_summary: LLM 调用失败（耗时 %.2fs）: %s", elapsed, e, exc_info=True)
            summary_text = (
                f"会话结束。共 {total_rounds} 轮对话。"
                f"使用了以下工具：{', '.join(tool_names) if tool_names else '无'}。"
                "感谢您的咨询，如有其他问题欢迎随时联系。"
            )

        end_message = AIMessage(
            content=(
                f"📋 **会话总结**\n\n"
                f"{summary_text}\n\n"
                f"---\n"
                f"📊 会话统计: 共 {total_rounds} 轮对话 | "
                f"使用工具: {', '.join(tool_names) if tool_names else '无'}\n\n"
                f"感谢您的咨询！如有其他问题，欢迎随时联系我们。👋"
            )
        )
        return {"messages": [end_message]}

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
    print("=== Agent 智能客服测试 (v3.2.0 混合架构) ===")
    async for event in svc.astream(
        {"input": "针织毛衣如何保养？"}, session_config
    ):
        print(f"[{event['type']}] {event['data']}")
    print()
    await svc.close()


if __name__ == "__main__":
    asyncio.run(_test_agent())
