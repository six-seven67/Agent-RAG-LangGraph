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
    messages: Annotated[list[BaseMessage], add_messages]  # 存储对话历史消息列表，包含用户输入和AI回复；使用add_messages注解确保新消息能正确追加到列表中，保持对话连续性
    summary: str  # 当前会话的摘要信息，用于上下文理解和长期记忆；通过提取关键信息减少token消耗，提高响应效率
    summary_updated: bool  # 标记summary是否已更新，避免重复处理；防止在同一个会话周期内多次生成摘要造成资源浪费
    is_session_end: bool  # 用户请求结束会话 → 触发 session_end_summary；允许系统优雅地关闭会话并生成最终总结，提升用户体验
