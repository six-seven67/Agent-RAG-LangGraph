"""
RAG (Retrieval-Augmented Generation) 服务模块

该模块实现了基于检索增强生成的问答系统，主要功能包括：
1. 混合检索：结合向量检索和BM25关键词检索
2. 重排序：使用Reranker对检索结果进行精排
3. 上下文管理：支持对话历史记录
4. 文档去重：基于父文档内容的去重机制
"""

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableWithMessageHistory, RunnableLambda
from src.storage import get_history
from src.retrieval import VectorStoreService
from src.retrieval import RerankerService
from src.retrieval import BM25Retriever
from src.retrieval import HybridRetriever
from langchain_community.embeddings import DashScopeEmbeddings
import src.config as config
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_models.tongyi import ChatTongyi


def print_prompt(prompt):
    """
    打印提示信息，用于调试和展示 prompt 内容
    
    Args:
        prompt: 一个具有 to_string() 方法的对象，通常是 LangChain 的 PromptTemplate 对象
        
    Returns:
        返回传入的 prompt 参数，支持链式调用
    """
    # 打印等号分隔线，用于视觉分隔
    print("=" * 20)
    # 调用 prompt 对象的 to_string() 方法将其转换为字符串并打印
    print(prompt.to_string())
    # 打印等号分隔线，完成视觉分隔
    print("=" * 20)
    # 返回原始 prompt，支持链式调用
    return prompt


class RagService(object):
    """
    RAG 服务类
    
    提供完整的检索增强生成功能，包括文档检索、重排序、上下文管理和回答生成
    """
    
    def __init__(self):
        """
        初始化 RAG 服务组件
        
        主要初始化以下组件：
        1. 向量存储服务：用于文档的向量化存储和检索
        2. 提示模板：定义与LLM交互的prompt格式
        3. 聊天模型：用于生成最终回答的大语言模型
        4. 处理链：构建完整的RAG处理流程
        """
        # 初始化向量存储服务，使用DashScope嵌入模型
        self.vector_service = VectorStoreService(
            embedding=DashScopeEmbeddings(model=config.embedding_model_name)
        )
        
        # 定义聊天提示模板，包含系统指令、历史消息和用户输入
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", "请以我提供的已知参考资料为主，简洁和专业的回答用户问题。参考资料: {context}。"),
            ("system", "并且我提供用户的对话历史记录，如下："),
            MessagesPlaceholder("history"),
            ("user", "请回答用户提问：{input}")
        ])
        
        # 初始化通义千问聊天模型
        self.chat_model = ChatTongyi(model=config.chat_model_name)
        
        # 构建完整的RAG处理链
        self.chain = self.__get_chain()

    def __get_chain(self):
        """
        构建RAG处理链
        
        该方法创建了一个完整的处理流程：
        1. 接收用户输入
        2. 执行混合检索（向量+BM25）
        3. 对检索结果进行重排序
        4. 构建上下文信息
        5. 生成最终回答
        
        Returns:
            RunnableWithMessageHistory: 包含历史记录管理的完整处理链
        """
        # 获取向量检索器
        vector_retriever = self.vector_service.get_retriever()
        
        # 获取所有文档用于BM25检索
        all_docs = self.vector_service.get_all_documents()
        
        # 创建BM25关键词检索器
        bm25_retriever = BM25Retriever(all_docs)
        
        # 创建混合检索器，结合向量检索和BM25检索的优势
        hybrid_retriever = HybridRetriever(vector_retriever, bm25_retriever)

        @RunnableLambda
        def retrieve_and_rerank(input_dict: dict) -> str:
            """
            执行检索和重排序的核心函数
            
            Args:
                input_dict: 包含用户输入的字典，格式为 {"input": "用户问题"}
                
            Returns:
                str: 格式化后的上下文文本，供LLM生成回答使用
            """
            # 提取用户查询
            query = input_dict["input"]
            
            # 执行混合检索：结合向量语义检索和BM25关键词检索，使用RRF算法融合结果
            docs = hybrid_retriever.retrieve(query)
            
            # 如果检索到相关文档，则进行重排序以提高相关性
            if docs:
                docs = RerankerService().rerank(query, docs)
            
            # 如果没有找到相关文档，返回默认提示
            if not docs:
                return "无相关参考资料"

            # 用于跟踪已处理的父文档，避免重复内容
            seen_parents = set()
            # 存储格式化后的文档片段
            parts = []
            
            # 遍历重排序后的文档列表
            for doc in docs:
                # 获取文档的父内容和章节标题
                parent = doc.metadata.get("parent_content", "")
                title = doc.metadata.get("section_title", "")
                
                # 如果存在父内容且未处理过，则添加完整段落
                if parent and parent not in seen_parents:
                    seen_parents.add(parent)
                    if title:
                        # 如果有标题，添加标题前缀
                        parts.append(f"【{title}】\n{parent}")
                    else:
                        # 无标题时直接添加父内容
                        parts.append(parent)
                elif not parent:
                    # 没有父内容时，直接使用当前文档内容
                    parts.append(doc.page_content)

            # 用分隔符连接所有文档片段，形成完整的上下文
            return "\n\n---\n\n".join(parts)

        # 构建LangChain处理链
        chain = (
            # 第一步：通过retrieve_and_rerank函数获取上下文并赋值给context变量
            RunnablePassthrough.assign(context=retrieve_and_rerank)
            # 第二步：应用提示模板，将上下文、历史和用户输入组合成完整prompt
            | self.prompt_template
            # 第三步：打印prompt用于调试（可选）
            | print_prompt
            # 第四步：调用大语言模型生成回答
            | self.chat_model
            # 第五步：将模型输出解析为字符串
            | StrOutputParser()
        )

        # 包装处理链以支持对话历史记录管理
        conversation_chain = RunnableWithMessageHistory(
            chain,                          # 基础处理链
            get_history,                    # 获取历史记录的函数
            input_messages_key="input",     # 输入消息的键名
            history_messages_key="history", # 历史消息的键名
        )

        return conversation_chain


if __name__ == "__main__":
    """
    主程序入口，用于测试RAG服务功能
    """
    import src.config as config
    
    # 构建测试用户的会话配置
    session_config = config.build_session_config("test_user")
    
    # 创建RAG服务实例并执行测试查询
    res = RagService().chain.invoke({"input": "针织毛衣如何保养？"}, session_config)
    
    # 打印回答结果
    print(res)