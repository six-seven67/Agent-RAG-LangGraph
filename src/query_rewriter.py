"""
查询改写（Query Rewrite）模块

对短查询、歧义查询进行 LLM 驱动的自动扩展，提升检索召回质量。

核心场景：
- 短查询（< 10 字）：如「怎么洗」→ 扩展为包含具体材质、操作类型的完整问题
- 指代消解：如「那纯棉的呢？」→ 结合历史补全为「纯棉材质的洗涤方法是什么？」
- 模糊查询：如「买多大」→ 扩展为包含具体参数的查询

设计原则：
- 已经具体明确的查询保持原样（避免过度改写引入噪声）
- 结合对话历史进行上下文补全（多轮对话场景）
- 改写结果用于检索，原始查询保留用于最终回答生成
"""

from typing import List, Optional
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import BaseMessage
from src import config_data as config


REWRITE_SYSTEM_PROMPT = """你是一个查询优化专家。你的任务是将用户的模糊、简短或不完整的查询改写为清晰、具体的检索查询。

## 改写规则

1. **短查询扩展**（< 10 字）：补充关键词，将模糊查询扩展为完整的检索语句
   - 「怎么洗」→「不同材质衣物的洗涤方法、水温要求和注意事项」
   - 「买多大」→「根据身高体重选择合适尺码的推荐方法」

2. **指代消解**：如果对话历史中有上下文，将指代词替换为具体内容
   - 历史「针织毛衣如何保养？」→ 用户「那夏天穿的呢？」→ 改写「夏季服装的洗涤和保养方法」

3. **专业术语补充**：如果查询涉及具体领域，补充相关专业术语作为同义关键词
   - 「不掉色的衣服」→「衣物固色 防褪色 洗涤注意事项」

4. **保持简洁**：改写后的查询不超过 50 个字，保留原始意图
5. **不编造内容**：只基于用户查询和对话历史进行改写，不要添加不存在的信息

## 输出格式
直接输出改写后的查询文本，不要添加任何前缀、解释或标点符号包装。如果原查询已经足够清晰，直接返回原查询。"""


class QueryRewriter:
    """
    查询改写器

    使用 LLM 对用户查询进行智能扩展，提升后续检索的召回率和精确度。

    Attributes:
        model: LLM 模型实例
        min_length_for_rewrite: 触发改写的最小查询长度（字符数）
    """

    def __init__(
        self,
        model_name: str = None,
        min_length_for_rewrite: int = 15,
    ):
        """
        初始化查询改写器。

        Args:
            model_name: LLM 模型名，默认从配置读取
            min_length_for_rewrite: 短于此长度的查询强制改写
        """
        self.model = ChatTongyi(
            model=model_name or config.chat_model_name,
            temperature=0.0,  # 改写需要确定性，temperature=0
        )
        self.min_length_for_rewrite = min_length_for_rewrite

    def _format_history(self, messages: Optional[List]) -> str:
        """将历史消息格式化为可读文本。"""
        if not messages:
            return "（无历史对话）"

        lines = []
        for msg in messages[-4:]:  # 仅保留最近 4 轮
            if hasattr(msg, "type"):
                role = "用户" if msg.type == "human" else "助手"
                content = msg.content if hasattr(msg, "content") else str(msg)
            elif isinstance(msg, dict):
                role = "用户" if msg.get("role") == "user" else "助手"
                content = msg.get("content", "")
            else:
                continue
            # 截断过长内容
            if len(content) > 200:
                content = content[:200] + "..."
            lines.append(f"{role}: {content}")

        return "\n".join(lines) if lines else "（无历史对话）"

    def _should_rewrite(self, query: str) -> bool:
        """
        判断是否需要改写。

        规则：
        - 查询长度 < min_length_for_rewrite：强制改写（短查询）
        - 查询包含指代词：强制改写
        - 其他：不需要改写（查询已足够清晰）
        """
        if len(query.strip()) < self.min_length_for_rewrite:
            return True

        # 指代词检测
        reference_words = ["这个", "那个", "它", "他们", "她们", "这些", "那些",
                          "那", "这", "别的", "其他的", "还有", "另外"]
        for word in reference_words:
            if word in query:
                return True

        return False

    def rewrite(
        self,
        query: str,
        history_messages: Optional[List] = None,
        force: bool = False,
    ) -> str:
        """
        改写用户查询。

        Args:
            query: 原始用户查询
            history_messages: 对话历史消息列表（LangChain Message 或 dict）
            force: 是否强制改写（忽略自动判断）

        Returns:
            改写后的查询字符串
        """
        # 短路：查询已经足够清晰，无需改写
        if not force and not self._should_rewrite(query):
            return query

        # 构建改写提示
        history_text = self._format_history(history_messages)

        user_prompt = f"""## 对话历史
{history_text}

## 用户当前查询
{query}

请输出改写后的查询（仅输出改写文本）："""

        try:
            response = self.model.invoke(
                f"{REWRITE_SYSTEM_PROMPT}\n\n{user_prompt}"
            )
            rewritten = response.content if hasattr(response, "content") else str(response)
            rewritten = rewritten.strip().strip('"').strip("'").strip("。").strip()

            # 安全检查：改写后查询不应为空或过长
            if not rewritten or len(rewritten) < 2:
                return query
            if len(rewritten) > 100:
                rewritten = rewritten[:100]

            return rewritten
        except Exception as e:
            # 降级：改写失败时返回原查询
            print(f"Query rewrite failed: {e}")
            return query

    async def arewrite(
        self,
        query: str,
        history_messages: Optional[List] = None,
        force: bool = False,
    ) -> str:
        """
        异步版本：改写用户查询。

        Args:
            query: 原始用户查询
            history_messages: 对话历史消息列表
            force: 是否强制改写

        Returns:
            改写后的查询字符串
        """
        if not force and not self._should_rewrite(query):
            return query

        history_text = self._format_history(history_messages)

        user_prompt = f"""## 对话历史
{history_text}

## 用户当前查询
{query}

请输出改写后的查询（仅输出改写文本）："""

        try:
            response = await self.model.ainvoke(
                f"{REWRITE_SYSTEM_PROMPT}\n\n{user_prompt}"
            )
            rewritten = response.content if hasattr(response, "content") else str(response)
            rewritten = rewritten.strip().strip('"').strip("'").strip("。").strip()

            if not rewritten or len(rewritten) < 2:
                return query
            if len(rewritten) > 100:
                rewritten = rewritten[:100]

            return rewritten
        except Exception as e:
            print(f"Async query rewrite failed: {e}")
            return query


if __name__ == "__main__":
    # 简单测试
    rewriter = QueryRewriter()

    test_queries = [
        "怎么洗",           # 短查询，应改写
        "那纯棉的呢？",      # 指代消解
        "买多大",            # 短查询
        "针织毛衣如何保养？", # 已清晰，应保持
        "黄皮肤春天穿什么颜色好看？",  # 已清晰
    ]

    for q in test_queries:
        rewritten = rewriter.rewrite(q)
        status = "✏️ 已改写" if rewritten != q else "✅ 保持原样"
        print(f"[{status}] {q} → {rewritten}")
