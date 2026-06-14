"""RAG 管道 — 查询改写。

扩展：新增 RAG 变体（如多模态 RAG）在此添加新 service 文件。
"""

from src.rag.rewriter import QueryRewriter

__all__ = [
    "QueryRewriter",
]
