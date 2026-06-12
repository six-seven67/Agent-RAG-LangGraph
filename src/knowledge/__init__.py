"""知识库管理 — 文档解析、清洗、分块、上传、向量化入库。

v3.3.0: 多格式支持（TXT/PDF/DOCX/XLSX）、通用分块策略、原文件保存。
"""

from src.knowledge.service import KnowledgeBaseService, get_string_md5
from src.knowledge.splitter import split_text
from src.knowledge.parser import parse_document
from src.knowledge.cleaner import clean_text

__all__ = [
    "KnowledgeBaseService",
    "get_string_md5",
    "split_text",
    "parse_document",
    "clean_text",
]
