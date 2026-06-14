"""
意图分类 — 规则匹配快速路由

classify_intent 节点：基于关键词规则快速判断用户意图，
支持闲聊直达、会话结束检测，零 LLM 延迟。

适用场景：知识库文档问答 Agent。
"""

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, AIMessage

from src.agent.state import AgentState

logger = logging.getLogger("AgentService")


# ================================================================
# 规则匹配表
# ================================================================

# 闲聊关键词（短消息 + 匹配 → 零 LLM 直达）
CASUAL_CHAT_KEYWORDS = [
    "你好", "您好", "hi", "hello", "hey",
    "早上好", "中午好", "下午好", "晚上好",
    "谢谢", "感谢", "多谢",
    "哈哈", "嘿嘿", "呵呵",
    "在吗", "在不在", "在不",
]

# 会话结束关键词
END_SESSION_KEYWORDS = [
    "再见", "拜拜", "bye", "goodbye", "结束",
    "没有了", "没别的事了", "就这样", "好的谢谢",
    "谢谢你的帮助", "搞定",
]


# ================================================================
# 路由决策
# ================================================================

def route_intent(
    state: AgentState,
    count_rounds_func,
) -> Literal["direct_chat", "end_session", "continue"]:
    """classify_intent 后的路由：根据意图分类结果分发。

    - direct_chat: 闲聊问候，已注入友好回复，直接结束
    - end_session: 用户请求结束会话
    - continue: 正常流程，进入 summarize → agent 循环
    """
    if state.get("is_session_end", False):
        logger.info("路由决策: end_session → session_end_summary")
        return "end_session"

    messages = state.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg, AIMessage) and "[CHAT]" in str(last_msg.content):
            logger.info("路由决策: direct_chat → END（闲聊规则命中，直接返回）")
            return "direct_chat"

    logger.debug("路由决策: continue → summarize → agent")
    return "continue"


# ================================================================
# classify_intent 节点
# ================================================================

async def classify_intent_node(state: AgentState, count_rounds_func) -> dict:
    """意图分类节点：基于关键词规则快速判断用户意图。

    策略（无 LLM 调用，零延迟）:
    1. 提取最后一条用户消息
    2. 会话结束关键词 → 设置 is_session_end 标志
    3. 闲聊关键词（短消息）→ 注入友好回复
    4. 都不匹配 → 继续正常流程（summarize → agent ReAct）

    Args:
        state: 当前图状态
        count_rounds_func: 统计对话轮数的函数

    Returns:
        dict: 可能包含注入的 AIMessage 和/或 is_session_end 标志
    """
    messages = state.get("messages", [])
    rounds = count_rounds_func(messages)

    # 找到最后一条用户消息
    last_user_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg.content if hasattr(msg, "content") else str(msg)
            break

    if not last_user_msg:
        logger.debug("classify_intent: 无用户消息，跳过")
        return {}

    logger.debug("classify_intent: 分析用户消息（轮次=%d, 消息截断前=%s）",
                  rounds, last_user_msg[:60])

    msg_lower = last_user_msg.lower().replace(" ", "")

    # ---- 1. 会话结束检测 ----
    for keyword in END_SESSION_KEYWORDS:
        if keyword.lower() in msg_lower:
            if len(last_user_msg) <= 20:
                logger.info("classify_intent: 检测到结束意图（关键词='%s', 消息='%s'）",
                            keyword, last_user_msg)
                return {"is_session_end": True}

    # ---- 2. 闲聊检测 ----
    for keyword in CASUAL_CHAT_KEYWORDS:
        if keyword.lower() in msg_lower:
            if len(last_user_msg) <= 15:
                logger.info("classify_intent: 闲聊命中（关键词='%s', 消息='%s'）→ 直接友好回复",
                            keyword, last_user_msg[:60])
                chat_response = AIMessage(
                    content=(
                        "[CHAT] 你好！我是文档知识助手，可以基于你上传的文档内容回答问题。\n"
                        "如果你有任何关于文档的问题，请随时告诉我。"
                    )
                )
                return {"messages": [chat_response]}

    # ---- 3. 默认：继续正常流程 ----
    logger.debug("classify_intent: 无规则命中 → 进入 summarize → agent 流程")
    return {}
