"""
回答格式化后处理（v4.1 — 精简版）

对 LLM 输出的 Markdown 文本进行轻量规范化：
- 清理连续多余空行（最多保留1个空行）
- 兼容旧格式【】标题（向后兼容已存储的旧回答）
"""

import re


def format_answer_output(text: str) -> str:
    """对 LLM 输出的 Markdown 文本进行轻量规范化。

    处理策略（按顺序）：
    1. 首尾空白清理
    2. 旧格式【】标签转 Markdown 标题（向后兼容）
    3. 清理连续多余空行（3+ → 1 空行）
    4. 行首尾空白清理

    Args:
        text: LLM 原始输出文本

    Returns:
        规范化后的 Markdown 文本
    """
    if not text:
        return text

    # ---- Step 1: 预处理 ----
    text = text.strip()

    # ---- Step 2: 旧格式【】标签转 Markdown 标题（向后兼容）----
    text = re.sub(r'【核心结论】\s*\n?', '## 核心结论\n', text)
    text = re.sub(r'【补充提醒】\s*\n?', '## 补充提醒\n', text)
    text = re.sub(r'【信息来源】\s*\n?', '## 信息来源\n', text)

    # ---- Step 3: 清理连续多余空行（不留空行）----
    text = re.sub(r'\n{2,}', '\n', text)

    # ---- Step 4: 行首尾空白清理 ----
    text = re.sub(r'^[ \t]+', '', text, flags=re.MULTILINE)
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)

    return text
