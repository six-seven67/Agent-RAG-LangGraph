"""
工具: web_search — 联网搜索

通过 Tavily Search API 搜索互联网获取实时信息。
当知识库无法覆盖时效性问题时，Agent 可调用此工具补充外部知识。

设计原则:
- 工厂模式（与 search_kb 保持一致），方便注入配置
- 无 API Key 时自动降级为占位工具，不阻塞 Agent 启动
- 搜索结果格式化输出，含标题、摘要、来源 URL
"""

import os
from langchain_core.tools import tool


def make_web_search():
    """创建联网搜索工具（工厂模式）。

    自动检测 TAVILY_API_KEY 环境变量:
    - 已配置: 返回可用的 Tavily 搜索工具
    - 未配置: 返回占位工具，提示管理员配置

    Returns:
        配置好的 web_search 工具函数
    """
    api_key = os.getenv("TAVILY_API_KEY", "")

    if not api_key:
        @tool
        async def web_search(query: str) -> str:
            """搜索互联网获取实时/外部信息。

            适用场景:
            - 时效性问题（新闻、趋势、价格变动等）
            - 知识库中没有的最新信息
            - 需要外部验证的事实

            不适用场景:
            - 产品/服务知识 → 用 search_knowledge_base
            - 高频FAQ → 用 lookup_faq

            Args:
                query: 搜索查询字符串。

            Returns:
                格式化的搜索结果。
            """
            return "联网搜索功能未配置，请联系管理员设置 TAVILY_API_KEY。建议尝试 search_knowledge_base 检索知识库。"
        return web_search

    # ---- Tavily 可用时的完整实现 ----
    try:
        from tavily import TavilyClient
        tavily_client = TavilyClient(api_key=api_key)
    except ImportError:
        @tool
        async def web_search(query: str) -> str:
            """搜索互联网获取实时/外部信息（依赖未安装）。"""
            return "联网搜索依赖未安装（tavily-python），请联系管理员。建议尝试 search_knowledge_base。"
        return web_search

    @tool
    async def web_search(query: str) -> str:
        """搜索互联网获取实时/外部信息。

        适用场景:
        - 时效性问题（新闻、趋势、价格变动、天气等）
        - 知识库中没有的最新信息
        - 需要外部验证的事实
        - 用户明确要求联网搜索

        不适用场景:
        - 产品/服务知识 → 优先使用 search_knowledge_base
        - 高频FAQ（营业时间、退换货等） → 优先使用 lookup_faq

        Args:
            query: 搜索查询字符串。建议提取核心关键词，
                   去除礼貌用语和无关修饰，英文查询效果更佳。

        Returns:
            格式化的搜索结果，含标题、摘要、来源 URL，最多 5 条。
            若无结果返回 "未找到相关网络信息。"
        """
        try:
            response = tavily_client.search(
                query=query,
                search_depth="basic",
                max_results=5,
                include_answer=True,
            )

            answer = response.get("answer", "")
            results = response.get("results", [])

            if not results and not answer:
                return "未找到相关网络信息。建议尝试 search_knowledge_base 检索知识库。"

            parts = []

            # Tavily AI 摘要（如有）
            if answer:
                parts.append(f"📝 **AI 摘要**: {answer}")

            # 搜索结果列表
            if results:
                parts.append("🔗 **搜索结果**:")
                for i, r in enumerate(results[:5], 1):
                    title = r.get("title", "无标题")
                    url = r.get("url", "")
                    content = r.get("content", "")
                    # 截断过长内容
                    if len(content) > 200:
                        content = content[:200] + "..."
                    parts.append(f"{i}. **{title}**\n   {content}\n   来源: {url}")

            return "\n\n".join(parts)

        except Exception as e:
            error_msg = str(e)
            # 截断过长错误信息
            if len(error_msg) > 150:
                error_msg = error_msg[:150] + "..."
            return (
                f"联网搜索暂时失败: {error_msg}。\n"
                "请基于知识库回答用户问题，或告知用户暂时无法进行联网搜索。"
            )

    return web_search
