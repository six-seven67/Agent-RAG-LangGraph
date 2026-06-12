"""
数据清洗模块

根据文件类型对提取的原始文本进行简单清洗，去除解析过程中产生的噪声。

清洗规则：
- 所有格式: 合并多余空白行、去除控制字符、统一换行符
- PDF     : 去除页眉页脚碎片、修复断行连字
- DOCX    : 轻量清洗（python-docx 提取质量较好）
- XLSX    : 去除空行标记、压缩表格空白
- TXT     : 规范化空白字符

Usage:
    from src.knowledge.cleaner import clean_text
    cleaned = clean_text(raw_text, ".pdf")
"""

import re
import logging

logger = logging.getLogger("TextCleaner")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(_h)


def clean_text(text: str, filename: str) -> str:
    """
    对提取的原始文本进行清洗。

    Args:
        text: 原始文本内容
        filename: 文件名（用于判断文件类型）

    Returns:
        str: 清洗后的文本
    """
    if not text or not text.strip():
        return ""

    ext = _get_extension(filename)
    before_len = len(text)

    # ---- 通用清洗（所有格式） ----
    text = _remove_control_chars(text)
    text = _normalize_line_endings(text)
    text = _collapse_blank_lines(text)
    text = _normalize_whitespace(text)

    # ---- 按文件类型专项清洗 ----
    if ext == ".pdf":
        text = _clean_pdf(text)
    elif ext == ".xlsx":
        text = _clean_excel(text)

    text = text.strip()
    after_len = len(text)
    logger.info("清洗完成: filename=%s, %d → %d 字符 (%.1f%%)",
                filename, before_len, after_len,
                (after_len / before_len * 100) if before_len else 0)

    return text


def _get_extension(filename: str) -> str:
    idx = filename.rfind(".")
    if idx == -1:
        return ""
    return filename[idx:].lower()


# ================================================================
# 通用清洗函数
# ================================================================

def _remove_control_chars(text: str) -> str:
    """移除除换行/制表外的控制字符（\x00-\x08, \x0b-\x0c, \x0e-\x1f）。"""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)


def _normalize_line_endings(text: str) -> str:
    """统一换行符为 \n。"""
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _collapse_blank_lines(text: str) -> str:
    """将 3 个及以上的连续空行压缩为 2 个。"""
    return re.sub(r'\n{3,}', '\n\n', text)


def _normalize_whitespace(text: str) -> str:
    """合并行内多余空白（>2 个空格 → 1 个），保留换行。"""
    lines = []
    for line in text.split('\n'):
        lines.append(re.sub(r' {2,}', ' ', line))
    return '\n'.join(lines)


# ================================================================
# 按文件类型的专项清洗
# ================================================================

def _clean_pdf(text: str) -> str:
    """
    PDF 专项清洗：
    1. 修复断行连字：行尾连字符 "-" 后紧跟换行 → 合并
    2. 去除明显是页眉/页码的短行（< 6 字符且含数字）
    """
    # 修复断行连字: "exam-\nple" → "example"
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)

    # 去除疑似页码/页眉的孤立短行
    lines = text.split('\n')
    filtered = [
        line for line in lines
        if not (len(line) < 6 and re.search(r'\d', line) and not re.search(r'[^\d\s\-.,]', line))
    ]
    return '\n'.join(filtered)


def _clean_excel(text: str) -> str:
    """
    Excel 专项清洗：
    1. 去除纯 tab 行（空行经解析后变成 tab 字符序列）
    2. 压缩连续 tab（3 个以上 → 2 个）
    """
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        # 跳过仅含 tab 和空格的行
        if re.match(r'^[\t ]+$', line):
            continue
        # 压缩多余 tab
        line = re.sub(r'\t{3,}', '\t\t', line)
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)
