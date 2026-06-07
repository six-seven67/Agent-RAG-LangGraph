"""
工具: escalate_to_human — 转接人工客服

适用场景：知识库无匹配、用户要求转人工、投诉/退款/复杂售后。
"""

from langchain_core.tools import tool


@tool
def escalate_to_human(summary: str) -> str:
    """转接人工客服处理。

    在以下情况使用此工具：
    - 知识库中找不到相关信息
    - 用户明确要求转人工
    - 问题超出自动化客服的处理范围（如投诉、退款、复杂售后）

    Args:
        summary: 用户问题的简要总结，供人工客服快速了解上下文。

    Returns:
        转接确认消息。
    """
    return (
        "已转接人工客服。\n"
        f"问题摘要：{summary}\n"
        "人工客服将很快接入，请耐心等待。"
    )
