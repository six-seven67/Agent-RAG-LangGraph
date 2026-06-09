"""
Agent 模块 — v3.2.0 混合架构

模块结构:
  state.py      — AgentState TypedDict
  prompts.py    — System Prompts（AGENT / SUMMARIZE / SESSION_END）
  formatter.py  — 回答格式化后处理
  classifier.py — 意图分类规则 + classify_intent 节点
  streaming.py  — 流式事件追踪 + chunk 分类
  service.py    — AgentService 编排层（Graph 构建 + 节点 + 公共 API）
  tools/        — Agent 工具（search_kb / web_search / faq / escalate）
"""

from src.agent.service import AgentService
from src.agent.state import AgentState
from src.agent.formatter import format_answer_output

__all__ = [
    "AgentService",
    "AgentState",
    "format_answer_output",
]
