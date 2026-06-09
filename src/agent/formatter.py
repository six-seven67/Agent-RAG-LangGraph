"""
回答格式化后处理

对 LLM 输出的回答进行结构化格式化，确保：
- 【核心结论】标签规范化 + 段落分隔
- 中文层级序号（一、→（一）→ 1. → (1)）正确换行
- 【补充提醒】【信息来源】独立成段
"""

import re


def format_answer_output(text: str) -> str:
    """对 LLM 输出的回答进行格式化后处理，确保结构清晰、换行正确。

    处理策略（按顺序执行）：
    1. 预处理：移除开头多余空白
    2. 【核心结论】标签规范化（确保标签后换行，段落间空行）
    3. 第一层标题（一、二、三、…十、）前插入空行
    4. 第二层标题（（一）（二）…）前确保换行
    5. 第三层要点（1. 2. 3. ...）前确保换行
    6. 【补充提醒】【信息来源】标签前插入空行
    7. 尾处理：移除连续多余空行，保留单个空行分隔

    Args:
        text: LLM 原始输出文本

    Returns:
        格式化后的文本
    """
    if not text:
        return text

    # ---- Step 1: 预处理 ----
    text = text.strip()

    # ---- Step 2: 【核心结论】规范化 ----
    text = re.sub(r'【核心结论】\s*', '【核心结论】\n', text)
    text = re.sub(
        r'(【核心结论】\n[^\n]+?)\n?(?=[一二三四五六七八九十]、|（[一二三四五六七八九十]）)',
        r'\1\n',
        text
    )

    # ---- Step 3: 第一层标题（一、二、…十、）前空行 ----
    text = re.sub(r'([。！？\n])([一二三四五六七八九十])、(?=\S)', r'\1\n\n\2、', text)
    text = re.sub(r'\n([一二三四五六七八九十])、(?=\S)', r'\n\n\1、', text)
    text = re.sub(r'(【核心结论】\n[^\n]+?)\n([一二三四五六七八九十])、', r'\1\n\n\2、', text)

    # ---- Step 4: 第二层标题（（一）（二）…）前换行 ----
    text = re.sub(r'([^（\n])(（[一二三四五六七八九十\d]+）)', r'\1\n\2', text)
    text = re.sub(r'(?<!\n)(（[一二三四五六七八九十\d]+）)', r'\n\1', text)

    # ---- Step 5: 第三层要点（1. 2. 3. ...）前换行 ----
    text = re.sub(r'([^0-9\n])(\d+)\.\s*(?=[^\d])', r'\1\n\2. ', text)
    text = re.sub(r'(?<!\n)(\d+\.\s)', r'\n\1', text)

    # ---- Step 6: 【补充提醒】【信息来源】前空行 ----
    text = re.sub(r'([。！？\n])(【补充提醒】)', r'\1\n\n\2', text)
    text = re.sub(r'([。！？\n])(【信息来源】)', r'\1\n\n\2', text)
    text = re.sub(r'(?<!\n)(【补充提醒】)', r'\n\n\1', text)
    text = re.sub(r'(?<!\n)(【信息来源】)', r'\n\n\1', text)

    # ---- Step 7: 尾处理：清理多余空行 ----
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'^[ \t]+', '', text, flags=re.MULTILINE)
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)

    return text
