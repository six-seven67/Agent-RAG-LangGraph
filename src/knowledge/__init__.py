"""知识库管理 — 文档上传、MD5 去重、语义分块、向量化入库。

扩展：新增文档类型支持在此添加新的 splitter。
"""

from src.knowledge.service import KnowledgeBaseService, get_string_md5
from src.knowledge.splitter import split_by_structure

__all__ = [
    "KnowledgeBaseService",
    "get_string_md5",
    "split_by_structure",
]
