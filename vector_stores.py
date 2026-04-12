"""

"""
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings

import config_data as config


class VectorStoreService(object):
    """
    向量存储服务类

    提供向量存储的核心功能，包括：
    - 向量检索
    - 向量存储
    - 向量更新
    - 向量删除

    使用Chroma作为向量数据库存储嵌入向量
    使用阿里云DashScope的text-embedding-v4模型进行文本向量化
    """

    def __init__(self, embedding):
        self.embedding = embedding

        self.vector_store = Chroma(
            collection_name=config.collection_name,
            embedding_function=self.embedding,
            persist_directory=config.chroma_path,
        )

    def get_retriever(self):
        # 创建一个向量检索器
        return self.vector_store.as_retriever(search_kwargs={"k": config.similarity_threshold})

if __name__ == "__main__":
    # 创建一个向量存储服务实例
    vector_store = VectorStoreService(DashScopeEmbeddings(model="text-embedding-v4"))

    # 创建一个向量检索器
    retriever = vector_store.get_retriever().invoke("我的体重150斤，尺码推荐")
    print(retriever)