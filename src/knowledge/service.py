"""
知识库服务模块

该模块负责管理知识库的构建和维护，主要功能包括：
1. 文档上传与处理：接收文本数据并进行语义分块
2. MD5去重检查：防止相同内容重复上传
3. 向量存储：将分块后的文档存入 Chroma 向量数据库
4. 元数据管理：记录创建时间、操作者等信息

工作流程：
    原始文本 → MD5校验 → 语义分块 → 添加元数据 → 向量存储 → MD5记录
"""

import datetime
import hashlib
import os

from langchain_community.embeddings import DashScopeEmbeddings
import src.config as config
from langchain_chroma import Chroma
from datetime import datetime
from src.knowledge.splitter import split_by_structure


def check_md5(md5_str: str):
    """
    检查 MD5 哈希值是否已存在于记录文件中
    
    用于判断文档内容是否已经上传过，避免重复处理相同内容。
    
    Args:
        md5_str: 待检查的 MD5 哈希字符串
        
    Returns:
        bool: 如果 MD5 存在返回 True，否则返回 False
        
    Note:
        - 如果 MD5 文件不存在，会自动创建空文件并返回 False
        - 逐行比对 MD5 值，适用于小到中等规模的文件
    """
    # 检查 MD5 记录文件是否存在
    if not os.path.exists(config.md5_path):
        # 文件不存在时创建空文件
        open(config.md5_path, "w", encoding="utf-8").close()
        return False
    else:
        # 读取文件中的所有 MD5 值进行比对
        for line in open(config.md5_path, "r", encoding="utf-8").readlines():
            line = line.strip()  # 去除首尾空白字符
            if line == md5_str:
                return True  # 找到匹配的 MD5 值
        return False  # 未找到匹配项


def save_md5(md5_str):
    """
    保存 MD5 哈希值到记录文件
    
    将新处理的文档 MD5 值追加到记录文件末尾，用于后续的去重检查。
    
    Args:
        md5_str: 要保存的 MD5 哈希字符串
        
    Note:
        - 使用追加模式打开文件，每次写入一行
        - 自动添加换行符分隔不同的 MD5 值
    """
    with open(config.md5_path, "a", encoding="utf-8") as f:
        f.write(md5_str + "\n")


def get_string_md5(input_str: str, encoding="utf-8"):
    """
    计算字符串的 MD5 哈希值
    
    用于生成文档内容的唯一标识符，实现基于内容的去重机制。
    
    Args:
        input_str: 需要计算 MD5 的输入字符串
        encoding: 字符串编码格式，默认为 UTF-8
        
    Returns:
        str: MD5 哈希值的十六进制字符串表示（32位）
        
    Example:
        >>> get_string_md5("Hello World")
        'b10a8db164e0754105b7a99be72e3fe5'
    """
    # 将字符串按指定编码转换为字节序列
    input_str = input_str.encode(encoding)
    
    # 创建 MD5 对象
    md5_obj = hashlib.md5()
    
    # 更新 MD5 对象的数据
    md5_obj.update(input_str)
    
    # 返回十六进制格式的哈希值
    return md5_obj.hexdigest()


class KnowledgeBaseService(object):
    """
    知识库服务类
    
    提供完整的知识库管理功能，包括文档上传、分块处理、向量存储等。
    支持基于内容的去重检查和语义分块策略。
    """
    
    def __init__(self, collection_name: str = None):
        """
        初始化知识库服务

        创建 Chroma 向量数据库实例，配置嵌入模型和持久化存储路径。
        确保数据存储目录存在。

        Args:
            collection_name: Chroma collection 名称。
                            None 时使用默认配置。
                            传入自定义名称可实现用户隔离。
        """
        # 确保 Chroma 数据库的持久化目录存在
        os.makedirs(config.chroma_path, exist_ok=True)

        # 初始化 Chroma 向量数据库
        self.chroma = Chroma(
            collection_name=collection_name or config.collection_name,  # 集合名称，支持用户隔离
            embedding_function=DashScopeEmbeddings(
                model="text-embedding-v4"                        # 使用通义千问 v4 嵌入模型
            ),
            persist_directory=config.chroma_path                 # 向量数据持久化存储路径
        )

    def upload_bt_str(self, data, filename):
        """
        上传文本数据到知识库
        
        完整的文档处理流程：
        1. 计算内容 MD5 并检查是否重复
        2. 对文本进行语义分块处理
        3. 为每个分块添加元数据
        4. 批量添加到向量数据库
        5. 记录 MD5 值用于后续去重
        
        Args:
            data: 原始文本数据内容
            filename: 文件名，用于确定合适的分块策略
            
        Returns:
            str: 操作结果提示信息
            
        Raises:
            无显式异常抛出，错误信息通过返回值传达
            
        Note:
            - 相同内容的文档不会重复处理（基于 MD5 去重）
            - 分块策略根据文件类型和结构动态调整
            - 所有分块共享相同的创建时间和操作者信息
        """
        # 计算文档内容的 MD5 哈希值
        md5_str = get_string_md5(data)

        # 检查是否已存在相同内容的文档
        if check_md5(md5_str):
            return "文件已经存在，请勿重复上传"

        # 根据文档结构进行智能语义分块
        chunks = split_by_structure(data, filename)

        # 获取当前时间作为文档创建时间
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 准备批量插入的数据列表
        texts = []      # 存储分块文本内容
        metadatas = []  # 存储对应的元数据
        
        # 处理每个分块，构建标准化的数据结构
        for ch in chunks:
            # 提取分块的文本内容
            texts.append(ch["content"])
            
            # 获取分块的元数据并补充额外信息
            meta = ch["metadata"]
            meta["create_time"] = create_time    # 添加创建时间
            meta["operator"] = ""                # 添加操作者信息（当前为空）
            metadatas.append(meta)

        # 批量添加文本和元数据到向量数据库
        # Chroma 会自动计算每个文本的向量表示并存储
        self.chroma.add_texts(texts, metadatas=metadatas)
        
        # 保存 MD5 值，标记此内容已处理
        save_md5(md5_str)

        # 返回成功信息和分块数量
        return f"上传成功，共 {len(chunks)} 个语义块"
