"""
Agent 状态定义

AgentState — LangGraph StateGraph 节点间流转的共享数据。
"""

from typing import TypedDict, Annotated

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """Agent 状态 — 在 LangGraph 节点间流转的共享数据。

    v3.2.0 新增 is_session_end 字段，支持会话结束总结。
    """
    messages: Annotated[list[BaseMessage], add_messages]
    summary: str
    summary_updated: bool
    is_session_end: bool  # 用户请求结束会话 → 触发 session_end_summary
