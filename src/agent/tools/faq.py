"""
工具: lookup_faq — 查询常见问题（FAQ）库

高频常见问题优先使用此工具快速获取标准答案，无需完整知识库检索。
"""

from langchain_core.tools import tool


# FAQ 库（硬编码高频问题，后续可迁移到 Chroma FAQ collection）
FAQ_DB = {
    "营业时间": "我们的营业时间为：周一至周日 9:00 - 21:00，节假日另行通知。",
    "退换货": "支持 7 天无理由退换货（商品完好、不影响二次销售）。质量问题 15 天内免费换新。退换货请联系客服获取退换货地址。",
    "发货": "下单后 24 小时内发货，默认快递为中通/圆通。全国大部分地区 3-5 天送达。",
    "配送": "全国包邮（港澳台及偏远地区除外）。支持顺丰到付。",
    "支付": "支持微信支付、支付宝、银行卡转账。大额订单可对公转账。",
    "发票": "支持开具增值税普通发票和专用发票。请在订单确认时填写开票信息。",
    "售后": "商品出现质量问题，请在签收后 48 小时内联系客服，提供照片和订单号，我们会尽快处理。",
    "尺码": "请参考商品详情页的尺码表，如有疑问可联系客服提供身高体重推荐合适尺码。",
}


@tool
def lookup_faq(question: str) -> str:
    """查询常见问题（FAQ）库。

    对于高频常见问题（如营业时间、退换货政策、配送范围等），
    优先使用此工具快速获取标准答案，无需进行完整知识库检索。

    Args:
        question: 用户问题的精简表述。

    Returns:
        FAQ 匹配结果或提示无匹配。
    """
    question_lower = question.lower()
    for keyword, answer in FAQ_DB.items():
        if keyword in question_lower or keyword in question:
            return f"【FAQ - {keyword}】\n{answer}"

    return "FAQ 库中无匹配结果，建议使用 search_knowledge_base 进行深度检索。"
