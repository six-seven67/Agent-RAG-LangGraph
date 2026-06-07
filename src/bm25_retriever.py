"""
BM25 关键词检索器模块

基于 BM25 算法的稀疏检索（Sparse Retrieval），用于与向量检索（Dense Retrieval）
互补。BM25 擅长精确关键词匹配（专有名词、产品型号等），而向量检索擅长语义匹配。

使用 jieba 分词处理中文文本，实现标准 BM25 评分算法。
"""

import math
from typing import List, Dict, Set

import jieba
from langchain_core.documents import Document


class BM25Retriever:
    """
    BM25 关键词检索器

    使用 jieba 分词 + BM25 算法对文档进行关键词检索。
    专为中文文本设计，与向量检索互补。

    BM25 公式:
        score(q, d) = Σ IDF(qi) * (tf(qi, d) * (k1 + 1)) / (tf(qi, d) + k1 * (1 - b + b * |d| / avgdl))

    Attributes:
        k1 (float): 词频饱和度参数，默认 1.5
        b (float): 文档长度归一化参数，默认 0.75
        documents (List[Document]): 索引的文档列表
    """

    def __init__(self, documents: List[Document], k1: float = 1.5, b: float = 0.75):
        """
        初始化 BM25 检索器并构建倒排索引。

        Args:
            documents: 要索引的 LangChain Document 列表
            k1: 词频饱和度参数（典型值 1.2~2.0）
            b: 文档长度归一化参数（0 = 不归一化, 1 = 完全归一化）
        """
        self.k1 = k1
        self.b = b
        self.documents = documents
        self._build_index()

    def _tokenize(self, text: str) -> List[str]:
        """
        使用 jieba 对中文文本进行分词。

        Args:
            text: 待分词文本

        Returns:
            分词结果列表
        """
        # jieba 精确模式分词，过滤空字符串
        return [w.strip() for w in jieba.cut(text) if w.strip()]

    def _build_index(self):
        """构建倒排索引和文档统计信息。"""
        # 对所有文档分词
        self.doc_tokens: List[List[str]] = [
            self._tokenize(doc.page_content) for doc in self.documents
        ]
        self.doc_len: List[int] = [len(tokens) for tokens in self.doc_tokens]
        self.avgdl: float = (
            sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0.0
        )

        # 构建倒排索引: term -> {doc_id: term_frequency}
        self.inverted_index: Dict[str, Dict[int, int]] = {}
        for doc_id, tokens in enumerate(self.doc_tokens):
            for token in tokens:
                if token not in self.inverted_index:
                    self.inverted_index[token] = {}
                self.inverted_index[token][doc_id] = (
                    self.inverted_index[token].get(doc_id, 0) + 1
                )

        self.N: int = len(self.documents)

    def _idf(self, term: str) -> float:
        """
        计算词的逆文档频率（IDF）。

        使用 BM25 标准 IDF 公式（Robertson-Sparck Jones）:
            IDF = log((N - n + 0.5) / (n + 0.5) + 1)

        Args:
            term: 词语

        Returns:
            IDF 值
        """
        n = len(self.inverted_index.get(term, {}))
        return math.log((self.N - n + 0.5) / (n + 0.5) + 1)

    def _bm25_score(self, query_tokens: List[str], doc_id: int) -> float:
        """
        计算查询与指定文档的 BM25 得分。

        Args:
            query_tokens: 查询的分词结果
            doc_id: 文档 ID

        Returns:
            BM25 得分（非负数，0 表示完全不匹配）
        """
        score = 0.0
        doc_len = self.doc_len[doc_id]

        for token in query_tokens:
            if token in self.inverted_index and doc_id in self.inverted_index[token]:
                tf = self.inverted_index[token][doc_id]
                idf = self._idf(token)
                # BM25 核心公式
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (
                    1 - self.b + self.b * doc_len / self.avgdl
                )
                score += idf * numerator / denominator

        return score

    def retrieve(self, query: str, top_k: int = 10) -> List[Document]:
        """
        根据查询检索最相关的 top_k 个文档。

        Args:
            query: 查询文本
            top_k: 返回文档数量

        Returns:
            按 BM25 得分降序排列的文档列表
        """
        if not self.documents:
            return []

        query_tokens = self._tokenize(query)

        # 计算所有文档的 BM25 得分
        scores = []
        for doc_id in range(self.N):
            score = self._bm25_score(query_tokens, doc_id)
            if score > 0:
                scores.append((doc_id, score))

        # 按得分降序排列
        scores.sort(key=lambda x: x[1], reverse=True)

        return [self.documents[doc_id] for doc_id, _ in scores[:top_k]]

    def get_all_documents(self) -> List[Document]:
        """返回所有已索引的文档。"""
        return self.documents


if __name__ == "__main__":
    # 简单测试
    test_docs = [
        Document(page_content="针织毛衣的洗涤方式是用冷水手洗", metadata={"source": "wash.txt"}),
        Document(page_content="纯棉T恤可以直接机洗但要用温水", metadata={"source": "wash.txt"}),
        Document(page_content="真丝连衣裙需要干洗不能水洗", metadata={"source": "wash.txt"}),
    ]

    bm25 = BM25Retriever(test_docs)
    results = bm25.retrieve("毛衣怎么洗", top_k=2)
    for i, doc in enumerate(results):
        print(f"[{i}] {doc.page_content} | meta={doc.metadata}")
