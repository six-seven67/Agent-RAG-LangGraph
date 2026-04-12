"""
知识库服务模块
提供文件MD5校验、文档上传和向量存储等功能
用于RAG（检索增强生成）系统的知识库管理

主要功能：
- 文件去重：通过MD5校验避免重复上传相同内容的文件
- 文本分割：将长文档智能分割成适合向量化的文本块
- 向量化存储：使用阿里云DashScope Embeddings进行文本向量化，并存储到Chroma数据库
- 元数据管理：记录文件来源、创建时间等信息
"""
import datetime
import hashlib
import os

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config_data as config
from langchain_chroma import Chroma

from datetime import datetime

def check_md5(md5_str: str):
    """
    检查MD5值是否已存在于记录文件中
    
    用于判断文件是否已经被处理过，避免重复上传和处理相同内容的文件
    
    :param md5_str: 要检查的MD5字符串
    :return: bool - 如果MD5已存在返回True，否则返回False
    """
    # 如果MD5记录文件不存在，创建空文件并返回False（表示未找到）
    if not os.path.exists(config.md5_path):
        open(config.md5_path, "w", encoding="utf-8").close()
        return False
    else:
        # 读取MD5记录文件的每一行，检查是否存在匹配的MD5值
        for line in open(config.md5_path, "r", encoding="utf-8").readlines():
            line = line.strip()  # 去除首尾空白字符
            if line == md5_str:
                return True  # 找到匹配的MD5，返回True
        return False  # 遍历完所有行都未找到匹配，返回False


def save_md5(md5_str):
    """
    保存文件的MD5值到记录文件
    
    将处理过的文件的MD5值追加保存到文件中，用于后续去重检查
    
    :param md5_str: 要保存的MD5字符串
    :return: None
    """
    # 以追加模式打开MD5记录文件，写入新的MD5值并换行
    with open(config.md5_path, "a", encoding="utf-8") as f:
        f.write(md5_str + "\n")


def get_string_md5(input_str: str, encoding="utf-8"):
    """
    计算字符串的MD5哈希值
    
    使用MD5算法对输入字符串进行哈希计算，生成唯一的32位十六进制字符串
    用于文件内容去重和完整性校验
    
    :param input_str: 需要计算MD5的输入字符串
    :param encoding: 字符串编码方式，默认为UTF-8
    :return: str - MD5哈希值的十六进制字符串（32位）
    """
    # 将字符串按照指定编码转换为字节序列
    input_str = input_str.encode(encoding)

    # 创建MD5哈希对象
    md5_obj = hashlib.md5()
    # 更新哈希对象的内容
    md5_obj.update(input_str)
    # 返回MD5哈希值的十六进制表示
    return md5_obj.hexdigest()


class KnowledgeBaseService(object):
    """
    知识库服务类
    
    提供知识库的核心功能，包括：
    - 文档上传和处理
    - 文本分割
    - 向量化存储
    - 相似度检索
    
    使用Chroma作为向量数据库存储文档嵌入向量
    使用阿里云DashScope的text-embedding-v4模型进行文本向量化
    """

    def __init__(self):
        """
        初始化知识库服务
        
        设置向量数据库和文本分割器实例
        创建必要的目录结构并初始化组件
        """
        # 确保Chroma数据库的持久化目录存在，如果不存在则创建
        # exist_ok=True 表示目录已存在时不会抛出异常
        os.makedirs(config.chroma_path, exist_ok=True)
        
        # 初始化Chroma向量数据库
        # Chroma是一个开源的向量数据库，专门用于存储和检索嵌入向量
        self.chroma = Chroma(
            collection_name=config.collection_name,          # 集合名称，用于区分不同的知识库
            embedding_function=DashScopeEmbeddings(          # 嵌入函数，使用阿里云DashScope服务
                model="text-embedding-v4"                    # 使用text-embedding-v4模型，支持中文且效果较好
            ),
            persist_directory=config.chroma_path             # 持久化存储路径，确保数据在重启后不丢失
        )
        
        # 初始化递归字符文本分割器
        # RecursiveCharacterTextSplitter会尝试按多种分隔符依次分割文本，保持语义完整性
        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,                    # 每个文本块的最大字符数
            chunk_overlap=config.chunk_overlap,              # 相邻文本块之间的重叠字符数，避免信息被切断
            separators=config.separators,                    # 分隔符列表，按优先级依次尝试分割（如\n\n, \n, 。, ，等）
            length_function=len,                             # 计算文本长度的函数
        )

    def upload_bt_str(self, data, filename):
        """
        上传字节流数据到知识库
        
        处理上传的文件内容，完整流程包括：
        1. 计算文件内容的MD5值进行去重检查
        2. 如果文件未处理过，根据长度判断是否需要文本分割
        3. 对文本块进行向量化并存储到Chroma数据库
        4. 附加元数据（来源文件名、创建时间等）
        5. 保存MD5值到记录文件，防止重复上传
        
        :param data: 文件的文本内容（str类型）
        :param filename: 文件名，用于标识文档来源
        :return: str - 操作结果提示信息
        """
        # 第一步：计算上传内容的MD5值，用于去重判断
        md5_str = get_string_md5(data)
        
        # 第二步：检查该MD5是否已存在，避免重复处理相同内容
        if check_md5(md5_str):
            return "文件已经存在，请勿重复上传"

        # 第三步：根据文本长度决定是否进行分割
        # 如果文本长度超过设定的阈值，使用分割器进行智能分割
        if len(data) > config.max_split_char_number:
            # split_text方法会将长文本分割成多个符合chunk_size要求的文本块
            # 分割时会尽量保持句子和段落的完整性
            knowledge_chunks: list[str] = self.spliter.split_text(data)
        else:
            # 短文本不需要分割，直接放入列表中
            knowledge_chunks = [data]

        # 第四步：构建元数据字典，记录文档的相关信息
        metadata = {
            "source": filename,                                    # 文档来源文件名
            "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # 上传时间，格式化为可读字符串
            "operator": ""                                         # 操作人信息，可后续扩展
        }

        # 第五步：将文本块添加到Chroma向量数据库
        # add_texts会自动调用嵌入函数将文本转换为向量，并与元数据一起存储
        self.chroma.add_texts(
            knowledge_chunks,                                      # 要存储的文本块列表
            metadatas=[metadata for _ in knowledge_chunks],       # 为每个文本块附加相同的元数据
        )

        # 第六步：保存MD5值到记录文件，标记该内容已处理
        save_md5(md5_str)

        # 返回成功提示
        return "上传成功"

