"""
向量存储服务模块

该模块提供基于 Chroma 的向量数据库服务，主要功能包括：
1. 向量存储管理：使用 Chroma 持久化存储文档向量
2. 文档检索：支持相似度检索获取相关文档
3. 全量文档获取：用于构建 BM25 索引等场景

依赖：
- langchain_chroma: Chroma 向量数据库集成
- DashScopeEmbeddings: 阿里云通义千问嵌入模型
"""

from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
import src.config as config


class VectorStoreService(object):
    """
    向量存储服务类
    
    封装 Chroma 向量数据库的操作，提供文档存储、检索和管理功能
    """
    
    def __init__(self, embedding, collection_name: str = None):
        """
        初始化向量存储服务

        Args:
            embedding: 嵌入模型实例，用于将文本转换为向量表示
                      通常使用 DashScopeEmbeddings 或其他 LangChain 兼容的嵌入模型
            collection_name: Chroma collection 名称。
                            None 时使用默认配置（向后兼容）。
                            传入自定义名称可实现用户隔离（如 rag_user_{user_id}）。
        """
        # 保存嵌入模型实例，用于后续的向量转换操作
        self.embedding = embedding
        self.collection_name = collection_name or config.collection_name

        # 初始化 Chroma 向量数据库实例
        self.vector_store = Chroma(
            collection_name=self.collection_name,        # 集合名称，支持用户隔离
            embedding_function=self.embedding,           # 嵌入函数，用于文本向量化
            persist_directory=config.chroma_path,        # 持久化存储路径，确保数据不丢失
        )

    def get_retriever(self):
        """
        获取文档检索器
        
        返回一个配置好的检索器对象，可用于相似度搜索获取相关文档。
        检索器会根据配置的 top_k 参数返回最相关的 K 个文档。
        
        Returns:
            VectorStoreRetriever: LangChain 的向量存储检索器对象
                                 可通过 invoke() 方法执行相似度搜索
            
        Example:
            retriever = service.get_retriever()
            docs = retriever.invoke("用户查询")  # 返回最相关的 K 个文档
        """
        # 创建检索器并配置返回文档数量
        return self.vector_store.as_retriever(search_kwargs={'k': config.retrieval_top_k})

    def get_all_documents(self) -> list:
        """
        获取向量库中所有文档（用于构建 BM25 索引等）。

        该方法会一次性加载所有存储的文档，适用于需要全量文档处理的场景，
        如构建 BM25 关键词检索索引、批量处理等。

        Returns:
            list[Document]: 所有已存储的 LangChain Document 对象列表
                           每个文档包含 page_content 和 metadata 属性
        
        Note:
            - 对于大型向量库，此操作可能消耗较多内存
            - 返回的文档顺序可能与插入顺序不一致
        """
        # 从 Chroma 数据库中获取所有文档数据
        # Chroma 的 get() 方法返回字典，包含 'ids', 'documents', 'metadatas' 等键
        result = self.vector_store.get()
        
        # 导入 LangChain 文档类用于构建标准文档对象
        from langchain_core.documents import Document

        # 初始化文档列表
        docs = []
        
        # 检查是否有文档数据存在
        if result and result.get("documents"):
            # 遍历所有文档内容
            for i, content in enumerate(result["documents"]):
                # 获取对应的元数据，如果不存在则使用空字典
                metadata = result.get("metadatas", [{}])[i] if result.get("metadatas") else {}
                
                # 创建标准的 LangChain Document 对象
                # page_content: 文档文本内容
                # metadata: 文档元数据（如来源、标题等）
                docs.append(Document(page_content=content, metadata=metadata))
        
        return docs


if __name__ == '__main__':
    """
    主程序入口，用于测试向量存储服务功能
    """
    # 创建向量存储服务实例，使用 text-embedding-v4 模型
    vector_store = VectorStoreService(DashScopeEmbeddings(model='text-embedding-v4'))
    
    # 获取检索器并执行测试查询
    retriever = vector_store.get_retriever().invoke('test')
    
    # 打印检索结果
    print(retriever)
