"""
工具: search_knowledge_base — 检索知识库

通过工厂模式注入用户隔离的检索组件，
确保每个用户的 Agent 检索各自的知识库 collection。
"""

import asyncio

from langchain_core.tools import tool


def _clean_chinese_text(text: str) -> str:
    """清理中文文本的常见排版问题。

    修复文档切分或 AI 输出中的非法换行：
    - 《...》跨行 → 合并为一行
    - 中文标点附近非法换行 → 合并
    - 中文汉字间断行 → 合并
    - 数字与中文单位间断行 → 合并
    """
    if not text:
        return text

    import re

    # ---- Pass 1: 配对标点内换行 ----
    # 《...》跨行
    text = re.sub(r'《([^》\n]*)\n([^》]*)》', r'《\1\2》', text)
    text = re.sub(r'《([^》]*)\n', r'《\1', text)
    text = re.sub(r'\n([^《]*)》', r'\1》', text)

    # （...）跨行
    text = re.sub(r'（([^）\n]*)\n([^）]*)）', r'（\1\2）', text)
    text = re.sub(r'（([^）]*)\n', r'（\1', text)
    text = re.sub(r'\n([^（]*)）', r'\1）', text)

    # "...", 跨行
    text = re.sub(r'“([^”\n]*)\n([^”]*)”', r'“\1\2”', text)
    text = re.sub(r'“([^”]*)\n', r'“\1', text)
    text = re.sub(r'\n([^“]*)”', r'\1”', text)

    # ---- Pass 2: 中文标点附近的非法换行 ----
    # 合并中文标点后的换行，但保留接结构化内容时的合理段落分隔
    text = re.sub(r'([，、；：。！？])\s*\n\s*', r'\1', text)
    text = re.sub(
        r'([。！？])\n(?!\s*(?:[-*\d]|（|[A-Z]|[一二三四五六七八九十]、|【))',
        r'\1', text
    )

    # ---- Pass 3: 标点边界粘连 ----
    text = re.sub(r'([^\n\s])\s*\n\s*([《〈「『（("])', r'\1\2', text)
    text = re.sub(r'([》〉」』）)"\'])\s*\n\s*([^\n\s])', r'\1\2', text)

    # ---- Pass 4: 中文汉字之间的断行 ----
    text = re.sub(r'([一-鿿])\s*\n\s*([一-鿿])', r'\1\2', text)

    # ---- Pass 5: 数字被断开 ----
    text = re.sub(r'(\d)\s*\n\s*([一-鿿])', r'\1\2', text)
    text = re.sub(r'([一-鿿])\s*\n\s*(\d)', r'\1\2', text)

    # ---- Pass 6: 冒号后的断行 ----
    text = re.sub(r'([：:])\s*\n\s*', r'\1', text)

    # ---- Pass 7: 清理残留 ----
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'^[ \t]+', '', text, flags=re.MULTILINE)
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)

    return text


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
                # 清理中文排版问题
                parent = _clean_chinese_text(parent)
                header = f"【{title}】" if title else ""
                parts.append(f"{header}\n{parent}")
            elif not parent:
                parts.append(_clean_chinese_text(doc.page_content))

        if not parts:
            return "无相关参考资料"

        return "\n\n---\n\n".join(parts)

    return search_knowledge_base
