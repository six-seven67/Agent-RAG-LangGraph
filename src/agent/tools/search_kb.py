"""
工具: search_knowledge_base — 检索知识库

通过工厂模式注入用户隔离的检索组件，
确保每个用户的 Agent 检索各自的知识库 collection。
"""

import asyncio

from langchain_core.tools import tool


def make_search_knowledge_base(
    query_rewriter,
    hybrid_retriever,
    reranker,
):
    """创建 search_knowledge_base 工具（工厂模式）。

    通过闭包注入用户隔离的检索组件（query_rewriter / hybrid_retriever / reranker），
    确保每个用户的 Agent 检索各自的知识库 collection。

    Args:
        query_rewriter: QueryRewriter 实例（含 arewrite 方法）
        hybrid_retriever: HybridRetriever 实例（含 retrieve 方法）
        reranker: RerankerService 实例（含 arerank 方法）

    Returns:
        配置好的 search_knowledge_base 工具
    """
    @tool
    async def search_knowledge_base(query: str) -> str:
        """检索知识库获取与用户问题相关的文档资料。

        使用前会自动对查询进行改写扩展（指代消解、关键词补充），
        然后执行混合检索（向量 + BM25）和 Cross-Encoder 重排序，
        返回最相关的 Top-5 文档片段。

        Args:
            query: 检索查询字符串。应提取用户问题中的核心关键词，
                   去除礼貌用语和无关修饰。

        Returns:
            格式化后的相关文档内容。若无结果返回 "无相关参考资料"。
        """
        # Step 1: 查询改写
        rewritten_query = await query_rewriter.arewrite(query)

        # Step 2: 混合检索（CPU-bound → asyncio.to_thread）
        docs = await asyncio.to_thread(
            hybrid_retriever.retrieve, rewritten_query
        )

        # Step 3: 重排序
        if docs:
            docs = await reranker.arerank(rewritten_query, docs)

        if not docs:
            return "无相关参考资料"

        # Step 4: Parent-Child 展开 + 去重 + 格式化
        seen_parents = set()
        parts = []
        for doc in docs[:5]:  # 最多返回 5 条
            parent = doc.metadata.get("parent_content", "")
            title = doc.metadata.get("section_title", "")
            source = doc.metadata.get("source", "")

            if parent and parent not in seen_parents:
                seen_parents.add(parent)
                header = f"【{title}】" if title else ""
                parts.append(f"{header}\n{parent}")
            elif not parent:
                parts.append(doc.page_content)

        if not parts:
            return "无相关参考资料"

        return "\n\n---\n\n".join(parts)

    return search_knowledge_base
