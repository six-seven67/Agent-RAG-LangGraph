"""
混合检索器模块

将向量检索（Dense Retrieval）与 BM25 关键词检索（Sparse Retrieval）结合，
通过 Reciprocal Rank Fusion (RRF) 算法融合两路召回结果。

混合检索的优势：
- 向量检索：擅长语义理解，能匹配同义词和近义表达
- BM25 检索：擅长精确关键词匹配（专有名词、产品型号、人名等）
- RRF 融合：无需调参，自动平衡两路召回的重要性
"""

from typing import List, Dict

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from src.bm25_retriever import BM25Retriever
from src import config_data as config


class HybridRetriever:
    """
    混合检索器

    同时执行向量检索和 BM25 关键词检索，通过 RRF 算法融合排序。
    用于替换纯向量检索，提升对专有名词和精确匹配的召回能力。

    检索流程:
        用户查询 → 向量检索 Top-K + BM25 检索 Top-K → RRF 融合 → 返回 Top-K

    Attributes:
        vector_retriever (BaseRetriever): LangChain 向量检索器
        bm25_retriever (BM25Retriever): BM25 关键词检索器
        vector_k (int): 向量检索召回数量
        bm25_k (int): BM25 检索召回数量
        fusion_k (int): RRF 融合参数 k（默认 60）
    """

    def __init__(
        self,
        vector_retriever: BaseRetriever,
        bm25_retriever: BM25Retriever,
        vector_k: int = None,
        bm25_k: int = None,
        fusion_k: int = None,
    ):
        """
        初始化混合检索器。

        Args:
            vector_retriever: LangChain 向量检索引擎
            bm25_retriever: BM25 关键词检索引擎
            vector_k: 向量检索返回文档数，默认从配置读取
            bm25_k: BM25 检索返回文档数，默认从配置读取
            fusion_k: RRF 算法参数，默认 60
        """
        self.vector_retriever = vector_retriever
        self.bm25_retriever = bm25_retriever
        self.vector_k = vector_k or config.hybrid_vector_k
        self.bm25_k = bm25_k or config.hybrid_bm25_k
        self.fusion_k = fusion_k or config.hybrid_fusion_k

    @staticmethod
    def _reciprocal_rank_fusion(
        doc_lists: List[List[Document]],
        k: int = 60,
    ) -> List[Document]:
        """
        使用 Reciprocal Rank Fusion (RRF) 算法融合多个检索结果列表。

        RRF 公式:
            RRF_score(d) = Σ 1 / (k + rank_i(d))

        其中:
            - k 是平滑参数（默认 60），防止除零并使排名差异更平滑
            - rank_i(d) 是文档 d 在第 i 个检索器结果中的排名（从 0 开始）

        当同一个文档在两个检索器中分别排第 1 和第 3:
            RRF = 1/(60+1) + 1/(60+3) = 0.0164 + 0.0159 = 0.0323

        特点:
            - 无需手动设定权重，自动平衡各检索器的贡献
            - 排名越靠前贡献越大，但不会完全主导
            - k 越大，排名的影响越平滑（排名差异的权重越小）

        Args:
            doc_lists: 多个检索器返回的文档列表（每个列表已按相关性排序）
            k: RRF 平滑参数，默认 60

        Returns:
            按 RRF 得分降序排列的文档列表（已去重）
        """
        # 使用字典记录每个文档的 RRF 得分和文档对象
        # key: page_content（用于去重），value: (rrf_score, document)
        fused: Dict[str, tuple] = {}

        for doc_list in doc_lists:
            for rank, doc in enumerate(doc_list):
                # 使用 page_content 作为文档唯一标识进行去重
                key = doc.page_content
                rrf_score = 1.0 / (k + rank)

                if key in fused:
                    # 同一文档在多个检索器中都出现，累加 RRF 得分
                    prev_score, _ = fused[key]
                    fused[key] = (prev_score + rrf_score, doc)
                else:
                    fused[key] = (rrf_score, doc)

        # 按 RRF 得分降序排列
        sorted_docs = sorted(fused.values(), key=lambda x: x[0], reverse=True)
        return [doc for _, doc in sorted_docs]

    def retrieve(self, query: str, top_k: int = None) -> List[Document]:
        """
        执行混合检索。

        同时从向量检索引擎和 BM25 检索引擎获取结果，
        通过 RRF 算法融合后返回 top_k 个最相关文档。

        Args:
            query: 用户查询文本
            top_k: 返回的文档数量，默认从配置读取（reranker_top_n 用于后续精排）

        Returns:
            融合排序后的文档列表
        """
        top_k = top_k or config.hybrid_top_k

        # Step 1: 向量检索（语义匹配）
        vector_docs = self.vector_retriever.invoke(query)[: self.vector_k]

        # Step 2: BM25 检索（关键词匹配）
        bm25_docs = self.bm25_retriever.retrieve(query, top_k=self.bm25_k)

        # Step 3: RRF 融合两路结果
        fused_docs = self._reciprocal_rank_fusion(
            [vector_docs, bm25_docs],
            k=self.fusion_k,
        )

        return fused_docs[:top_k]

    def get_retriever(self):
        """
        返回一个可调用的检索器接口（兼容 LangChain retriever 调用方式）。

        Returns:
            self.retrieve 方法的绑定引用
        """
        return self.retrieve


if __name__ == "__main__":
    # 简单测试
    from langchain_community.embeddings import DashScopeEmbeddings
    from src.vector_stores import VectorStoreService

    embedding = DashScopeEmbeddings(model=config.embedding_model_name)
    vector_service = VectorStoreService(embedding=embedding)
    vector_retriever = vector_service.get_retriever()

    # 从 vector store 获取所有文档构建 BM25 索引
    all_docs = vector_service.get_all_documents()
    bm25 = BM25Retriever(all_docs)

    hybrid = HybridRetriever(vector_retriever, bm25)

    results = hybrid.retrieve("针织毛衣如何保养？")
    print(f"混合检索结果: {len(results)} 个文档")
    for i, doc in enumerate(results):
        print(f"  [{i}] {doc.page_content[:80]}...")
