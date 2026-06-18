"""
流式事件处理

将 LangGraph stream_mode="messages" 输出分类为前端可消费的 SSE 事件：
token / tool_start / tool_end / summarize / session_end / thinking
"""

import logging

from langchain_core.messages import (
    AIMessage, AIMessageChunk, ToolMessage, SystemMessage
)

logger = logging.getLogger("AgentService")


def init_event_tracking(service):
    """初始化事件追踪状态（每次 astream/ainvoke 调用时重置）。

    将追踪字典挂载到 service 实例上，避免污染 AgentState。
    """
    service._seen_tool_starts = set()            # 已发送 tool_start 的工具名（去重用）
    service._tool_call_id_to_name = {}           # tool_call_id → tool_name 映射


def extract_tool_name(tc) -> str:
    """从 tool_call 条目中提取工具名（兼容 dict / ToolCall / ToolCallChunk）。

    LangChain 不同版本/模式下 tool_calls 条目类型不同：
    - dict: {"name": "...", "args": {...}}
    - ToolCall: 有 .name 属性
    - ToolCallChunk: 有 .name 属性（可能为 None）
    """
    if isinstance(tc, dict):
        return (tc.get("name") or "").strip()
    return (getattr(tc, "name", None) or "").strip()


def classify_chunk(msg, metadata: dict, service) -> dict:
    """将 LangGraph stream 输出分类为前端可消费的事件。

    Args:
        msg: 流式消息（AIMessageChunk / ToolMessage / AIMessage / SystemMessage）
        metadata: LangGraph 流元数据
        service: AgentService 实例（含事件追踪状态）

    Returns:
        {"type": "token"|"tool_start"|"tool_end"|"summarize"|"session_end"|"thinking", "data": ...}
    """
    # Case 1: 对话摘要更新（SystemMessage 包含摘要）
    if isinstance(msg, SystemMessage) and "[对话历史摘要]" in str(msg.content):
        return {"type": "summarize", "data": ""}

    # Case 1b: 幻觉校验失败 → 通知前端重新生成
    if isinstance(msg, SystemMessage) and "[系统指令] 上一轮回答存在事实问题" in str(msg.content):
        return {"type": "hallucination", "data": "检测到回答可能不准确，正在重新生成..."}

    # Case 2: AI 文本 token（流式）
    if isinstance(msg, AIMessageChunk):
        if msg.content:
            return {"type": "token", "data": msg.content}

        if hasattr(msg, "tool_calls") and msg.tool_calls:
            valid_tools = []
            for tc in msg.tool_calls:
                name = extract_tool_name(tc)
                if name:
                    tc_id = ""
                    if isinstance(tc, dict):
                        tc_id = (tc.get("id") or "").strip()
                    else:
                        tc_id = (getattr(tc, "id", None) or "").strip()
                    if tc_id:
                        service._tool_call_id_to_name[tc_id] = name
                    if name not in service._seen_tool_starts:
                        service._seen_tool_starts.add(name)
                        valid_tools.append({
                            "name": name,
                            "args": tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                        })
                    else:
                        logger.debug("_classify_chunk: 跳过重复 tool_start（%s）", name)

            if valid_tools:
                logger.info("_classify_chunk: tool_start → %s", [t["name"] for t in valid_tools])
                return {"type": "tool_start", "data": {"tools": valid_tools}}

        return {"type": "thinking", "data": ""}

    # Case 3: AI 完整消息（非流式，含 tool_calls）
    if isinstance(msg, AIMessage):
        content = msg.content if hasattr(msg, "content") else ""
        if "📋 **会话总结**" in str(content):
            return {"type": "session_end", "data": ""}

        if "[HALLUCINATION_FAIL]" in str(content):
            return {"type": "hallucination", "data": "检测到回答可能不准确，正在重新生成..."}

        # 闲聊直接回复（[CHAT] 标记 → 去除标记后作为 token 输出）
        if "[CHAT]" in str(content):
            clean = str(content).replace("[CHAT] ", "")
            return {"type": "token", "data": clean}

        if hasattr(msg, "tool_calls") and msg.tool_calls:
            valid_tools = []
            for tc in msg.tool_calls:
                name = extract_tool_name(tc)
                if name:
                    tc_id = ""
                    if isinstance(tc, dict):
                        tc_id = (tc.get("id") or "").strip()
                    else:
                        tc_id = (getattr(tc, "id", None) or "").strip()
                    if tc_id:
                        service._tool_call_id_to_name[tc_id] = name
                    if name not in service._seen_tool_starts:
                        service._seen_tool_starts.add(name)
                        valid_tools.append({
                            "name": name,
                            "args": tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                        })

            if valid_tools:
                logger.info("_classify_chunk: tool_start（完整消息）→ %s", [t["name"] for t in valid_tools])
                return {"type": "tool_start", "data": {"tools": valid_tools}}

        return {"type": "thinking", "data": ""}

    # Case 4: 工具执行结果
    if isinstance(msg, ToolMessage):
        content = msg.content if hasattr(msg, "content") else str(msg)
        preview = content[:100] + "..." if len(content) > 100 else content

        tool_name = getattr(msg, "name", None) or ""
        tool_name = tool_name.strip()
        if not tool_name:
            tc_id = getattr(msg, "tool_call_id", None) or ""
            tool_name = service._tool_call_id_to_name.get(tc_id, "")
        if not tool_name:
            logger.warning("_classify_chunk: ToolMessage 无工具名！tool_call_id=%s, msg=%s",
                           getattr(msg, "tool_call_id", "?"), str(msg)[:200])
            tool_name = "unknown"

        service._seen_tool_starts.discard(tool_name)

        logger.info("_classify_chunk: tool_end → %s（预览: %s）", tool_name, preview[:60])
        return {
            "type": "tool_end",
            "data": {
                "tool": tool_name,
                "result_preview": preview,
            },
        }

    # Case 5: 其他
    return {"type": "thinking", "data": ""}
