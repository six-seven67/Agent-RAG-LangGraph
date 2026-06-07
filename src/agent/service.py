"""
Agent 智能客服服务 — 基于 LangChain create_agent

与 RAG 管线的核心区别：
- RAG: 固定管线「检索 → 生成」，无论什么问题都走同一流程
- Agent: LLM 自主决策 → 是否查库、是否追问、是否转人工

架构:
  create_agent(model, tools, checkpointer, system_prompt)
    ├── agent 节点: LLM 分析 + 决策（回答 / 调用工具）
    ├── tools 节点: 执行工具调用（search_knowledge_base 等）
    └── AsyncSqliteSaver: 持久化对话历史（含 tool 消息）

流式输出:
  使用 graph.astream(stream_mode="messages") 捕获：
  - AIMessageChunk → token 事件（逐字输出）
  - AIMessage(tool_calls) → tool_start 事件
  - ToolMessage → tool_end 事件

Usage:
    svc = AgentService(user_id=1)
    async for event in svc.astream({"input": "..."}, config):
        print(event)  # {"type": "token", "data": "..."} | {"type": "tool_start", ...}
"""

import asyncio
import os
from typing import TypedDict, Annotated, AsyncIterator, Iterator

from langchain.agents import create_agent
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.message import add_messages

from langchain_core.messages import (
    BaseMessage, HumanMessage, AIMessage, AIMessageChunk, ToolMessage
)
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models.tongyi import ChatTongyi

from src.retrieval import VectorStoreService
from src.retrieval import RerankerService
from src.retrieval import BM25Retriever
from src.retrieval import HybridRetriever
from src.rag import QueryRewriter
from src.agent.tools import make_search_knowledge_base, escalate_to_human, lookup_faq
import src.config as config

# ---- 持久化根目录（使用 config 统一路径）----
STORAGE_ROOT = config.chat_history_path


# ================================================================
# Agent System Prompt
# ================================================================

AGENT_SYSTEM_PROMPT = """你是一个专业的智能客服助手，拥有知识库检索和人工转接能力。

## 核心行为准则

1. **知识库优先**：回答产品/服务/知识性问题时，必须先使用 search_knowledge_base 工具检索知识库，基于检索结果回答。
2. **FAQ 快速匹配**：对于高频常见问题（营业时间、退换货、发货、支付等），优先使用 lookup_faq 工具。
3. **不编造信息**：知识库和 FAQ 中都没有的信息，明确告知用户你不知道，不要编造答案。
4. **追问澄清**：用户问题模糊或不完整时，先追问具体需求，再进行检索。
5. **转人工**：遇到投诉、退款、复杂售后等超出知识库范围的问题时，使用 escalate_to_human 工具。
6. **简洁专业**：回答简洁明了，分点列出关键信息，语气友好。

## 工作流程

1. 分析用户问题类型
2. 高频常见问题 → lookup_faq
3. 知识性问题 → search_knowledge_base
4. 检索结果充分 → 基于结果回答
5. 检索结果不足 → 追问澄清或转人工
6. 闲聊/问候 → 直接友好回复（无需调用工具）

## 注意事项

- 用户可能使用简称或口语化表达，请理解其真实意图
- 多轮对话中注意上下文，理解指代关系
- 回答时引用知识库中的具体信息，让用户感到可信
"""


# ================================================================
# AgentService
# ================================================================

class AgentService:
    """Agent 智能客服服务（LangGraph ReAct Agent 后端）。

    使用 LangGraph create_react_agent 构建具备工具调用能力的 Agent。
    LLM 自主决定何时检索、何时追问、何时转人工。

    每个用户使用独立的 SQLite 数据库文件 + Chroma collection，实现用户隔离。
    """

    def __init__(self, user_id: int = None):
        """初始化 Agent 服务和所有子组件。

        Args:
            user_id: 用户 ID，用于用户隔离。
                     None 时使用默认配置（向后兼容）。
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

        # ---- LLM（streaming=True 以支持流式输出）----
        self.chat_model = ChatTongyi(
            model=config.chat_model_name,
            streaming=True,
        )

        # ---- 创建工具（注入用户隔离的检索组件）----
        self._search_tool = make_search_knowledge_base(
            self.query_rewriter,
            self.hybrid_retriever,
            self.reranker,
        )
        self.tools = [self._search_tool, lookup_faq, escalate_to_human]

        # ---- Graph（延迟编译）----
        self._graph = None
        self._checkpointer_conn = None
        self._checkpointer = None

        # ---- 用户隔离：SQLite checkpoint 数据库路径 ----
        db_name = f"checkpoints_agent_user_{user_id}.db" if user_id is not None else "checkpoints_agent_default.db"
        self._checkpoint_db_path = os.path.join(STORAGE_ROOT, db_name)
        os.makedirs(os.path.dirname(self._checkpoint_db_path), exist_ok=True)

    # ================================================================
    # Graph 构建
    # ================================================================

    def _build_graph(self):
        """构建 Agent graph。

        使用 langchain.agents.create_agent 创建：
        - agent 节点（LLM + tools）
        - tools 节点（执行工具调用）
        - 条件路由（tool_call → tools → agent，否则 → END）
        """
        graph = create_agent(
            model=self.chat_model,
            tools=self.tools,
            checkpointer=self._checkpointer,
            system_prompt=AGENT_SYSTEM_PROMPT,
        )
        return graph

    async def _ensure_graph(self):
        """延迟初始化：创建 checkpointer 并构建 agent graph。"""
        if self._graph is not None:
            return self._graph

        import aiosqlite

        self._checkpointer_conn = await aiosqlite.connect(self._checkpoint_db_path)
        self._checkpointer = AsyncSqliteSaver(self._checkpointer_conn)
        self._graph = self._build_graph()

        return self._graph

    # ================================================================
    # 流式事件处理
    # ================================================================

    @staticmethod
    def _classify_chunk(msg, metadata: dict) -> dict:
        """将 LangGraph stream 输出分类为前端可消费的事件。

        Args:
            msg: 流式消息（AIMessageChunk / ToolMessage / AIMessage）
            metadata: LangGraph 流元数据

        Returns:
            {"type": "token"|"tool_start"|"tool_end"|"thinking", "data": ...}
        """
        # Case 1: AI 文本 token
        if isinstance(msg, AIMessageChunk):
            if msg.content:
                return {"type": "token", "data": msg.content}
            # tool_calls 在 AIMessageChunk 中以增量形式出现
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                return {
                    "type": "tool_start",
                    "data": {
                        "tools": [
                            {"name": tc.get("name", ""), "args": tc.get("args", {})}
                            for tc in msg.tool_calls
                        ]
                    }
                }
            return {"type": "thinking", "data": ""}

        # Case 2: AI 完整消息（含 tool_calls）
        if isinstance(msg, AIMessage):
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                return {
                    "type": "tool_start",
                    "data": {
                        "tools": [
                            {"name": tc.get("name", ""), "args": tc.get("args", {})}
                            for tc in msg.tool_calls
                        ]
                    }
                }
            return {"type": "thinking", "data": ""}

        # Case 3: 工具执行结果
        if isinstance(msg, ToolMessage):
            content = msg.content if hasattr(msg, 'content') else str(msg)
            # 截断过长内容用于前端展示
            preview = content[:100] + "..." if len(content) > 100 else content
            return {
                "type": "tool_end",
                "data": {
                    "tool": getattr(msg, 'name', 'unknown'),
                    "result_preview": preview,
                }
            }

        # Case 4: 其他
        return {"type": "thinking", "data": ""}

    # ================================================================
    # 异步接口
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

        config_lg = {"configurable": {"thread_id": session_id}}

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config_lg,
        )

        # 提取最后一条 AI 消息的内容（跳过 tool 消息）
        all_messages = result.get("messages", [])
        for msg in reversed(all_messages):
            if isinstance(msg, AIMessage) and msg.content:
                return msg.content
        return ""

    async def astream(
        self, input_data: dict, session_config: dict
    ) -> AsyncIterator[dict]:
        """异步流式调用，逐事件产出。

        使用 LangGraph 的 stream_mode="messages" 捕获所有消息事件，
        分类为 token / tool_start / tool_end / thinking 事件。

        Args:
            input_data: {"input": "用户查询"}
            session_config: {"configurable": {"session_id": "..."}}

        Yields:
            事件 dict:
            - {"type": "token", "data": "文本片段"}
            - {"type": "tool_start", "data": {"tools": [{"name": "...", "args": {...}}]}}
            - {"type": "tool_end", "data": {"tool": "...", "result_preview": "..."}}
            - {"type": "thinking", "data": ""}
        """
        graph = await self._ensure_graph()
        query = input_data["input"]
        session_id = session_config["configurable"]["session_id"]

        config_lg = {"configurable": {"thread_id": session_id}}

        async for msg, metadata in graph.astream(
            {"messages": [HumanMessage(content=query)]},
            config_lg,
            stream_mode="messages",
        ):
            event = self._classify_chunk(msg, metadata)
            # 跳过空的 thinking 事件（减少噪音）
            if event["type"] == "thinking" and not event["data"]:
                continue
            yield event

    # ================================================================
    # 文本流兼容接口（用于 SSE 等纯文本场景）
    # ================================================================

    async def astream_text(
        self, input_data: dict, session_config: dict
    ) -> AsyncIterator[str]:
        """异步流式调用，仅产出纯文本 token（向后兼容 RAG 接口）。

        对于 tool_start / tool_end 事件，产出可读的状态描述文本。

        Args:
            input_data: {"input": "用户查询"}
            session_config: {"configurable": {"session_id": "..."}}

        Yields:
            文本字符串（token 或状态描述）
        """
        async for event in self.astream(input_data, session_config):
            if event["type"] == "token":
                yield event["data"]
            elif event["type"] == "tool_start":
                tools_info = event.get("data", {}).get("tools", [])
                tool_names = [t.get("name", "") for t in tools_info]
                yield f"\n🔍 正在调用工具: {', '.join(tool_names)}...\n"
            elif event["type"] == "tool_end":
                preview = event.get("data", {}).get("result_preview", "")
                yield f"\n✅ 工具执行完成\n"
            elif event["type"] == "thinking":
                pass  # 跳过 thinking

    # ================================================================
    # 同步兼容接口（Streamlit 等）
    # ================================================================

    def sync_invoke(self, input_data: dict, session_config: dict) -> str:
        """同步兼容包装器（非流式）。"""
        return asyncio.run(self.ainvoke(input_data, session_config))

    def sync_stream(self, input_data: dict, session_config: dict) -> Iterator[dict]:
        """同步兼容包装器（流式，产事件 dict）。"""
        import queue
        import threading

        q: queue.Queue = queue.Queue()

        async def producer():
            try:
                async for event in self.astream(input_data, session_config):
                    q.put(("event", event))
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
                yield {"type": "error", "data": payload}
                break
            else:
                yield payload

        thread.join(timeout=5)

    def sync_stream_text(self, input_data: dict, session_config: dict) -> Iterator[str]:
        """同步兼容包装器（流式，纯文本）。"""
        import queue
        import threading

        q: queue.Queue = queue.Queue()

        async def producer():
            try:
                async for chunk in self.astream_text(input_data, session_config):
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
                pass


# ================================================================
# 测试入口
# ================================================================

async def _test_agent():
    """异步测试 Agent 服务。"""
    svc = AgentService()
    session_config = config.build_session_config("test_agent_user")
    print("=== Agent 智能客服测试 ===")
    async for event in svc.astream(
        {"input": "针织毛衣如何保养？"}, session_config
    ):
        print(f"[{event['type']}] {event['data']}")
    print()
    await svc.close()


if __name__ == "__main__":
    asyncio.run(_test_agent())
