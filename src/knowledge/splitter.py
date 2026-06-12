"""
语义分块器模块 — 通用 Parent-Child 父子文档分块

适用于大多数文档场景的分块策略：
1. Parent 块（较粗粒度）: 保留完整语义上下文，用于 LLM 生成回答
2. Child 块（较细粒度）: 精确的检索单元，用于向量相似度匹配

检索时用 Child 做相似度匹配（精准），返回时带上 Parent 的完整内容（上下文充足）。

分块流程：
    原始文本
      → RecursiveCharacterTextSplitter(parent_size=2000) → Parent 块
      → 每个 Parent 内部再用 RecursiveCharacterTextSplitter(child_size=500) → Child 块
      → Child.metadata.parent_content = 所属 Parent 的完整文本

配置参数（config.py）:
    - parent_chunk_size / parent_chunk_overlap
    - child_chunk_size  / child_chunk_overlap
    - separators: 通用的自然语言边界优先级列表
"""

import logging
from typing import List

from langchain_text_splitters import RecursiveCharacterTextSplitter

import src.config as config

logger = logging.getLogger("Splitter")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(_h)


def split_text(text: str, source: str = "") -> List[dict]:
    """
    对任意文本执行 Parent-Child 父子文档语义分块。

    两层结构:
    - Parent: 较大的语义段落，提供完整上下文
    - Child:  较小的检索单元，从 Parent 中切分出来
    - 每个 Child 通过 metadata["parent_content"] 关联到其 Parent

    短文本处理:
    - 若文本长度 ≤ child_chunk_size，作为单一块（既是 parent 也是 child）
    - 若文本长度 ≤ parent_chunk_size，只做一层切分（全部为 child，parent_content 指向全文）

    Args:
        text: 待分块的文本内容
        source: 来源文件名，写入 metadata["source"]

    Returns:
        List[dict]: 所有分块，每个元素包含:
            - content (str): 分块文本
            - metadata (dict):
                - source:         来源文件名
                - chunk_type:     "parent" | "child"
                - chunk_index:    全局序号
                - parent_index:   所属 Parent 的序号（child 有，parent 为 None）
                - parent_content: Parent 的完整文本（child 有，parent 指向自身）
                - child_count:    该 Parent 下的 Child 数量（parent 有）

    Example:
        >>> chunks = split_text("很长的文档...", source="report.pdf")
        >>> # chunks[0] = Parent 0, chunks[1:4] = Child 0-0, 0-1, 0-2
        >>> # 检索时命中 Child → 取出 parent_content → 喂给 LLM
    """
    if not text or not text.strip():
        return []

    text_len = len(text)
    logger.info("开始分块: source=%s, text_len=%d", source, text_len)

    # ---- 情况 1: 文本极短，不需要分层 ----
    if text_len <= config.child_chunk_size:
        logger.info("文本较短（%d ≤ child_chunk_size=%d），单块处理", text_len, config.child_chunk_size)
        return [{
            "content": text,
            "metadata": {
                "source": source,
                "chunk_type": "child",
                "chunk_index": 0,
                "parent_index": 0,
                "parent_content": text,
            }
        }]

    # ---- 情况 2: 文本中等长度，只做一层 Child 切分 ----
    if text_len <= config.parent_chunk_size:
        logger.info("文本中等（%d ≤ parent_chunk_size=%d），单层 Child 切分", text_len, config.parent_chunk_size)
        child_splitter = _make_child_splitter()
        chunks = []
        for i, child_text in enumerate(child_splitter.split_text(text)):
            chunks.append({
                "content": child_text,
                "metadata": {
                    "source": source,
                    "chunk_type": "child",
                    "chunk_index": i,
                    "parent_index": 0,
                    "parent_content": text,  # 全文作为 parent context
                }
            })
        logger.info("分块完成: %d 个 child（单层）", len(chunks))
        return chunks

    # ---- 情况 3: 文本较长，完整 Parent → Child 两层切分 ----
    parent_splitter = _make_parent_splitter()
    child_splitter = _make_child_splitter()

    parent_texts = parent_splitter.split_text(text)
    logger.info("第一层 Parent 切分: %d 个 parent 块", len(parent_texts))

    chunks = []
    global_idx = 0

    for p_idx, parent_text in enumerate(parent_texts):
        # 添加 Parent 块
        chunks.append({
            "content": parent_text,
            "metadata": {
                "source": source,
                "chunk_type": "parent",
                "chunk_index": global_idx,
                "parent_index": p_idx,
                "parent_content": parent_text,
                "child_count": 0,  # 下面填充
            }
        })
        parent_chunk_idx = global_idx  # 记录 Parent 在 chunks 中的位置
        global_idx += 1

        # 从 Parent 中切出 Child 块
        child_texts = child_splitter.split_text(parent_text)
        for _c_idx, child_text in enumerate(child_texts):
            chunks.append({
                "content": child_text,
                "metadata": {
                    "source": source,
                    "chunk_type": "child",
                    "chunk_index": global_idx,
                    "parent_index": p_idx,
                    "parent_content": parent_text,  # 关键: 关联完整 Parent 上下文
                }
            })
            global_idx += 1

        # 回填 Parent 的 child_count
        chunks[parent_chunk_idx]["metadata"]["child_count"] = len(child_texts)

    logger.info("分块完成: %d 个 parent + %d 个 child = %d 总计",
                len(parent_texts), global_idx - len(parent_texts), len(chunks))
    return chunks


def _make_parent_splitter() -> RecursiveCharacterTextSplitter:
    """创建 Parent 层的分块器（较大粒度，保留上下文）。"""
    return RecursiveCharacterTextSplitter(
        chunk_size=config.parent_chunk_size,
        chunk_overlap=config.parent_chunk_overlap,
        separators=config.separators,
        length_function=len,
    )


def _make_child_splitter() -> RecursiveCharacterTextSplitter:
    """创建 Child 层的分块器（较小粒度，精确检索）。"""
    return RecursiveCharacterTextSplitter(
        chunk_size=config.child_chunk_size,
        chunk_overlap=config.child_chunk_overlap,
        separators=config.separators,
        length_function=len,
    )
