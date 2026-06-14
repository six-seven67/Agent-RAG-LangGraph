"""
Agent Graph 节点实现

每个节点是一个独立的 async 函数，接受 svc (AgentService) 和 state (AgentState)，
返回 dict 用于更新状态。节点实现与 Graph 编排解耦，便于单独测试和维护。

节点列表:
- classify_intent_wrapper:   委托给 classifier 模块（规则路由）
- summarize_node:            轮次 + Token 双阈值触发对话压缩
- agent_node:                LLM ReAct 决策（绑定工具）
- tools_node:                ToolNode 懒加载执行
- session_end_summary_node:  会话结束全局总结
- hallucination_check_node:  验证回答是否基于检索内容
"""

import logging
import time

from langchain_core.messages import (
    HumanMessage, AIMessage, ToolMessage, SystemMessage
)
from langgraph.prebuilt import ToolNode

from src.agent.state import AgentState
from src.agent.prompts import (
    AGENT_SYSTEM_PROMPT, SUMMARIZE_PROMPT,
    SESSION_END_SUMMARY_PROMPT, HALLUCINATION_CHECK_PROMPT,
)
import src.config as config

logger = logging.getLogger("AgentService")


# ================================================================
# classify_intent_wrapper
# ================================================================

async def classify_intent_wrapper(svc, state: AgentState) -> dict:
    """委托给 classifier 模块的规则路由节点。"""
    from src.agent.classifier import classify_intent_node
    return await classify_intent_node(state, svc._count_rounds)


# ================================================================
# summarize_node
# ================================================================

async def summarize_node(svc, state: AgentState) -> dict:
    """对话压缩节点：轮次 + Token 双阈值触发。

    触发条件（任一满足即进入压缩流程）:
    1. 对话轮次达到 agent_summary_trigger_rounds 阈值
    2. 对话历史总字符数达到 agent_summary_token_threshold 阈值

    进入后仍需通过间隔和消息数守卫才能实际执行压缩。
    """
    t0 = time.monotonic()
    messages = state.get("messages", [])
    rounds = svc._count_rounds(messages)
    threshold = config.agent_summary_trigger_rounds
    keep_recent = config.agent_summary_keep_recent
    max_chars = config.agent_summary_max_chars
    token_threshold = config.agent_summary_token_threshold

    # ---- 短路检查 1: 双阈值触发 ----
    # Token 阈值检查（额外触发源，不依赖轮次）
    total_chars = sum(
        len(msg.content) if hasattr(msg, 'content') and msg.content else 0
        for msg in messages
    )
    estimated_tokens = total_chars // 2  # 中文 ≈ 2 chars/token
    token_triggered = estimated_tokens >= token_threshold

    if not token_triggered and rounds < threshold:
        logger.debug(
            "summarize: 短路（轮次=%d < 阈值=%d, tokens≈%d < 阈值=%d）",
            rounds, threshold, estimated_tokens, token_threshold,
        )
        return {"summary_updated": False}

    if token_triggered and rounds < threshold:
        logger.info(
            "summarize: Token 阈值触发（tokens≈%d >= %d, 轮次仅=%d）",
            estimated_tokens, token_threshold, rounds,
        )

    # ---- 短路检查 2: 最小间隔 ----
    if rounds - svc._last_summary_rounds < config.agent_summary_min_interval_rounds:
        logger.debug("summarize: 短路（距上次总结仅 %d 轮 < 最小间隔 %d）",
                     rounds - svc._last_summary_rounds, config.agent_summary_min_interval_rounds)
        return {"summary_updated": False}

    # ---- 短路检查 3: 消息数不足 ----
    if len(messages) <= keep_recent:
        logger.debug("summarize: 短路（消息数=%d ≤ 保留数=%d）", len(messages), keep_recent)
        return {"summary_updated": False}

    old_messages = list(messages[:-keep_recent])
    recent_messages = list(messages[-keep_recent:])

    logger.info("summarize: 触发总结（轮次=%d, tokens≈%d, 旧消息=%d条, 保留=%d条）",
                 rounds, estimated_tokens, len(old_messages), len(recent_messages))

    # ---- 格式化旧消息 ----
    old_text_parts = []
    for msg in old_messages:
        role = "用户" if isinstance(msg, HumanMessage) else "助手"
        content = msg.content if hasattr(msg, "content") else str(msg)
        if content and len(content) > 300:
            content = content[:300] + "..."
        old_text_parts.append(f"[{role}]: {content}")
    old_text = "\n".join(old_text_parts)

    # ---- 增量合并指令 ----
    existing_summary = state.get("summary", "")
    existing_instruction = (
        f"当前已有摘要: 「{existing_summary}」\n"
        "请将其与以下新对话合并，更新为新的运行摘要。"
    ) if existing_summary else "这是首次生成摘要。"

    # ---- 调用 LLM ----
    try:
        prompt = SUMMARIZE_PROMPT.format(
            existing_summary_instruction=existing_instruction,
            max_chars=max_chars,
            old_messages_text=old_text,
        )
        logger.debug("summarize: 调用摘要 LLM（prompt 长度=%d）", len(prompt))
        response = await svc.summary_model.ainvoke(prompt)
        new_summary = response.content if hasattr(response, "content") else str(response)
        new_summary = new_summary.strip()
        if len(new_summary) > max_chars * 2:
            new_summary = new_summary[:max_chars * 2]
        elapsed = time.monotonic() - t0
        logger.info("summarize: 完成（%d字, 耗时 %.2fs）", len(new_summary), elapsed)
    except Exception as e:
        logger.error("summarize: LLM 调用失败，跳过总结: %s", e, exc_info=True)
        return {"summary_updated": False}

    svc._last_summary_rounds = rounds
    summary_msg = SystemMessage(
        content=f"[对话历史摘要]\n{new_summary}\n---\n以下是最近的对话："
    )
    return {
        "messages": [summary_msg] + recent_messages,
        "summary": new_summary,
        "summary_updated": True,
    }


# ================================================================
# agent_node
# ================================================================

async def agent_node(svc, state: AgentState) -> dict:
    """LLM ReAct 决策节点：调用 LLM 决定回答问题或调用工具。

    绑定 svc.tools（search_knowledge_base + web_search），
    让 LLM 自主判断是否需要检索。
    """
    t0 = time.monotonic()
    messages = state.get("messages", [])
    summary = state.get("summary", "")
    rounds = svc._count_rounds(messages)

    system_content = AGENT_SYSTEM_PROMPT.format(
        summary=summary if summary else "（暂无对话摘要）"
    )
    full_messages = [SystemMessage(content=system_content)] + list(messages)

    if svc._model_with_tools is None:
        svc._model_with_tools = svc.chat_model.bind_tools(svc.tools)
    model_with_tools = svc._model_with_tools
    logger.debug("agent: 调用 LLM（消息数=%d, 轮次=%d, 工具数=%d）",
                  len(full_messages), rounds, len(svc.tools))

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
            "messages": [AIMessage(content="抱歉，我暂时无法处理您的请求，请稍后再试。")]
        }
    return {"messages": [response]}


# ================================================================
# tools_node
# ================================================================

async def tools_node(svc, state: AgentState) -> dict:
    """ToolNode 懒加载执行节点。

    首次调用时创建 ToolNode 实例并缓存到 svc._tool_node。
    """
    if svc._tool_node is None:
        logger.info("首次创建 ToolNode（触发检索组件懒加载）")
        svc._tool_node = ToolNode(svc.tools)
    return await svc._tool_node.ainvoke(state)


# ================================================================
# session_end_summary_node
# ================================================================

async def session_end_summary_node(svc, state: AgentState) -> dict:
    """会话结束总结节点：生成全局摘要和会话统计。"""
    t0 = time.monotonic()
    messages = state.get("messages", [])
    total_rounds = svc._count_rounds(messages)

    tool_names = set()
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_names.add(getattr(msg, "name", "unknown"))

    logger.info("session_end_summary: 开始生成全局总结（轮次=%d, 消息数=%d, 工具=%s）",
                 total_rounds, len(messages), list(tool_names))

    # ---- 格式化对话文本 ----
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

    # ---- 调用 LLM ----
    try:
        prompt = SESSION_END_SUMMARY_PROMPT.format(conversation_text=conversation_text)
        logger.debug("session_end_summary: 调用 LLM（prompt 长度=%d）", len(prompt))
        response = await svc.summary_model.ainvoke(prompt)
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
# hallucination_check_node
# ================================================================

async def hallucination_check_node(svc, state: AgentState) -> dict:
    """幻觉校验节点：验证 AI 回答是否严格基于检索到的文档内容。

    触发条件（由路由 _should_continue 保证）:
    - agent 返回了最终回答（无 tool_calls）
    - 历史中存在 ToolMessage（发生过检索）

    跳过条件:
    - 已达最大重试次数（hallucination_retry_count >= 1）
    - 回答内容为空
    - 回答 < 30 字（很可能是追问澄清）
    - 历史中无 ToolMessage（纯闲聊）

    校验失败时:
    - 注入 SystemMessage 指示 agent 重新回答
    - 递增 hallucination_retry_count
    """
    messages = state.get("messages", [])
    retry_count = state.get("hallucination_retry_count", 0)

    # ---- 已达最大重试 ----
    if retry_count >= 1:
        logger.info("hallucination_check: 已达最大重试次数，跳过")
        return {}

    # ---- 提取最后一条 AI 回答 ----
    last_answer = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            last_answer = msg.content
            break

    if not last_answer:
        logger.debug("hallucination_check: 无 AI 回答，跳过")
        return {"hallucination_retry_count": retry_count + 1}

    if len(last_answer) < 30:
        logger.debug("hallucination_check: 回答过短（%d字），可能是追问澄清，跳过", len(last_answer))
        return {"hallucination_retry_count": retry_count + 1}

    # ---- 提取检索上下文 ----
    context_parts = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.content:
            content = msg.content
            # 截断过长内容以控制 prompt 长度
            if len(content) > 800:
                content = content[:800] + "..."
            context_parts.append(content)

    if not context_parts:
        logger.debug("hallucination_check: 无检索上下文，跳过")
        return {"hallucination_retry_count": retry_count + 1}

    context = "\n---\n".join(context_parts)

    # ---- LLM 事实核查 ----
    t0 = time.monotonic()
    try:
        prompt = HALLUCINATION_CHECK_PROMPT.format(
            context=context[:3000],  # 截断保护
            answer=last_answer[:2000],
        )
        response = await svc.summary_model.ainvoke(prompt)
        result = response.content.strip() if hasattr(response, "content") else str(response).strip()
        elapsed = time.monotonic() - t0
    except Exception as e:
        logger.error("hallucination_check: LLM 调用失败: %s", e, exc_info=True)
        return {"hallucination_retry_count": retry_count + 1}

    # ---- 解析结果 ----
    if result.upper().startswith("FAIL"):
        reason = result.split("\n", 1)[1].strip() if "\n" in result else "回答可能包含未经验证的信息"
        logger.warning("hallucination_check: FAIL（耗时 %.2fs）— %s", elapsed, reason)

        correction_msg = SystemMessage(content=(
            f"[系统指令] 上一轮回答存在事实问题：{reason}\n"
            "请严格基于之前的工具检索结果重新回答。只使用文档中明确存在的信息，"
            "不要编造任何数据、名称或结论。如果文档中确实没有相关信息，请明确告知用户。"
        ))
        return {
            "messages": [correction_msg],
            "hallucination_retry_count": retry_count + 1,
        }

    logger.info("hallucination_check: PASS（耗时 %.2fs）", elapsed)
    return {"hallucination_retry_count": retry_count + 1}
