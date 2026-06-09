"""
意图分类 — 规则匹配快速路由

classify_intent 节点：基于关键词规则快速判断用户意图，
支持 FAQ 直达、转人工、会话结束检测，零 LLM 延迟。
"""

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, AIMessage

from src.agent.state import AgentState

logger = logging.getLogger("AgentService")


# ================================================================
# 规则匹配表
# ================================================================

# 关键词 → FAQ 答案（与 lookup_faq 工具保持一致）
FAQ_KEYWORDS = {
    "营业时间": "我们的营业时间为：周一至周日 9:00 - 21:00，节假日另行通知。",
    "退换货": "支持 7 天无理由退换货（商品完好、不影响二次销售）。质量问题 15 天内免费换新。退换货请联系客服获取退换货地址。",
    "发货": "下单后 24 小时内发货，默认快递为中通/圆通。全国大部分地区 3-5 天送达。",
    "配送": "全国包邮（港澳台及偏远地区除外）。支持顺丰到付。",
    "支付": "支持微信支付、支付宝、银行卡转账。大额订单可对公转账。",
    "发票": "支持开具增值税普通发票和专用发票。请在订单确认时填写开票信息。",
    "售后": "商品出现质量问题，请在签收后 48 小时内联系客服，提供照片和订单号，我们会尽快处理。",
    "尺码": "请参考商品详情页的尺码表，如有疑问可联系客服提供身高体重推荐合适尺码。",
}

# 转人工关键词
ESCALATE_KEYWORDS = ["投诉", "退款", "转人工", "人工客服", "找人工", "找客服", "我要投诉"]

# 会话结束关键词
END_SESSION_KEYWORDS = [
    "再见", "拜拜", "bye", "goodbye", "结束", "谢谢你的帮助",
    "没有了", "没别的事了", "就这样", "好的谢谢", "谢谢", "搞定",
]


# ================================================================
# 路由决策
# ================================================================

def route_intent(
    state: AgentState,
    count_rounds_func,
) -> Literal["faq_direct", "end_session", "continue"]:
    """classify_intent 后的路由：根据意图分类结果分发。

    - faq_direct: FAQ 答案已注入 messages，直接结束
    - end_session: 用户请求结束会话
    - continue: 正常流程，进入 summarize → agent 循环
    """
    if state.get("is_session_end", False):
        logger.info("路由决策: end_session → session_end_summary")
        return "end_session"

    messages = state.get("messages", [])
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg, AIMessage) and "[FAQ]" in str(last_msg.content):
            logger.info("路由决策: faq_direct → END（FAQ 规则命中，直接返回）")
            return "faq_direct"

    logger.debug("路由决策: continue → summarize → agent")
    return "continue"


# ================================================================
# classify_intent 节点
# ================================================================

async def classify_intent_node(state: AgentState, count_rounds_func) -> dict:
    """意图分类节点：基于关键词规则快速判断用户意图。

    策略（无 LLM 调用，零延迟）:
    1. 提取最后一条用户消息
    2. FAQ 关键词匹配 → 直接注入 FAQ 答案
    3. 转人工关键词 → 注入转人工响应
    4. 结束会话关键词 → 设置 is_session_end 标志
    5. 都不匹配 → 继续正常流程

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

    # ---- 1. 会话结束检测 ----
    msg_lower = last_user_msg.lower().replace(" ", "")
    for keyword in END_SESSION_KEYWORDS:
        if keyword.lower() in msg_lower:
            if len(last_user_msg) <= 20:
                logger.info("classify_intent: 检测到结束意图（关键词='%s', 消息='%s'）",
                            keyword, last_user_msg)
                return {"is_session_end": True}

    # ---- 2. FAQ 关键词匹配 ----
    for keyword, answer in FAQ_KEYWORDS.items():
        if keyword in last_user_msg:
            logger.info("classify_intent: FAQ 命中（关键词='%s', 消息='%s'）→ 直接注入答案",
                        keyword, last_user_msg[:60])
            faq_response = AIMessage(
                content=f"【FAQ - {keyword}】\n{answer}\n\n💡 如果您需要更详细的信息，请随时告诉我。"
            )
            return {"messages": [faq_response]}

    # ---- 3. 转人工关键词 ----
    for keyword in ESCALATE_KEYWORDS:
        if keyword in last_user_msg:
            logger.info("classify_intent: 转人工命中（关键词='%s', 消息='%s'）→ 注入转接响应",
                        keyword, last_user_msg[:60])
            escalate_response = AIMessage(
                content=(
                    "已为您转接人工客服。\n"
                    f"问题摘要：{last_user_msg[:100]}\n"
                    "人工客服将很快接入，请耐心等待。\n"
                    "⏰ 工作时间：周一至周日 9:00 - 21:00"
                )
            )
            return {"messages": [escalate_response]}

    # ---- 4. 默认：继续正常流程 ----
    logger.debug("classify_intent: 无规则命中 → 进入 summarize → agent 流程")
    return {}
