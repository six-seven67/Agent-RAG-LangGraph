"""
知识库服务模块

该模块负责管理知识库的构建和维护，主要功能包括：
1. 文档上传与处理：接收文本数据并进行语义分块
2. MD5去重检查：防止相同内容重复上传（由 API 层 MySQL 统一管理）
3. 向量存储：将分块后的文档存入 Chroma 向量数据库
4. 元数据管理：记录创建时间、操作者等信息

工作流程：
    原始文本 → 数据清洗 → 语义分块 → 添加元数据 → 向量存储

v3.2.1 修复：
- 移除文件级 MD5 去重（与 API 层 MySQL 去重冲突，导致用户隔离失效）
- upload_bt_str 改为异步，Chroma 操作通过 asyncio.to_thread 避免阻塞 event loop
- 返回结构化 dict 替代纯文本消息
- 支持传入 operator 信息
- Chroma 写入失败时回滚已写入数据
- 新增 delete_by_doc_id 方法支持按文档 ID 清理向量数据

v3.3.0:
- 接入通用 Parent-Child 语义分块（splitter.split_text）
- Parent 块提供完整上下文，Child 块用于精确检索
"""

import asyncio
import hashlib
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_chroma import Chroma

import src.config as config
from src.knowledge.splitter import split_text

logger = logging.getLogger("KnowledgeBaseService")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(_h)


def get_string_md5(input_str: str, encoding: str = "utf-8") -> str:
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
    input_bytes = input_str.encode(encoding)
    md5_obj = hashlib.md5()
    md5_obj.update(input_bytes)
    return md5_obj.hexdigest()


class KnowledgeBaseService(object):
    """
    知识库服务类

    提供完整的知识库管理功能，包括文档上传、分块处理、向量存储等。
    支持基于内容的去重检查和语义分块策略。

    v3.2.1:
    - 去重由 API 层 MySQL 统一管理，本层不再维护全局 md5.text
    - upload_bt_str 返回结构化结果
    - 异步化 Chroma 操作
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
        os.makedirs(config.chroma_path, exist_ok=True)

        self.collection_name = collection_name or config.collection_name
        self.chroma = Chroma(
            collection_name=self.collection_name,
            embedding_function=DashScopeEmbeddings(
                model="text-embedding-v4"
            ),
            persist_directory=config.chroma_path,
        )

    # ================================================================
    # 公共 API
    # ================================================================

    async def upload_bt_str(
        self,
        data: str,
        filename: str,
        md5_str: Optional[str] = None,
        operator: str = "",
    ) -> dict:
        """
        上传文本数据到知识库（异步）

        完整的文档处理流程：
        1. 计算内容 MD5
        2. 对文本进行语义分块处理
        3. 为每个分块添加元数据
        4. 异步批量添加到向量数据库
        5. 返回结构化结果

        Args:
            data: 原始文本数据内容
            filename: 文件名，用于确定合适的分块策略
            md5_str: 预计算的 MD5（API 层传入），None 时自动计算
            operator: 操作者标识（用户名或用户 ID）

        Returns:
            dict: {"success": bool, "chunk_count": int, "doc_id": str, "message": str}

        Note:
            - 去重检查由 API 层通过 MySQL 完成，本方法不重复校验
            - Chroma 写入在后台线程池执行，不阻塞事件循环
            - 写入失败时尝试回滚已写入的数据
        """
        if md5_str is None:
            md5_str = get_string_md5(data)

        # 生成文档级唯一 ID（用于后续删除操作）
        doc_id = md5_str

        # 通用语义分块
        chunks = split_text(data, source=filename)

        # 获取当前时间作为文档创建时间
        create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 准备批量插入的数据列表
        texts = []
        metadatas = []
        ids = []

        for i, ch in enumerate(chunks):
            texts.append(ch["content"])
            meta = ch["metadata"]
            meta["create_time"] = create_time
            meta["operator"] = operator
            meta["doc_id"] = doc_id        # 关联文档 ID，用于批量删除
            meta["chunk_index"] = i         # 分块序号
            metadatas.append(meta)
            ids.append(f"{doc_id}_{i}")     # 唯一 ID

        logger.info(
            "上传文档: filename=%s, doc_id=%s, chunks=%d, operator=%s",
            filename, doc_id, len(chunks), operator or "(未指定)",
        )

        # 异步写入 Chroma（线程池中执行，避免阻塞事件循环）
        try:
            await asyncio.to_thread(
                self.chroma.add_texts, texts, metadatas=metadatas, ids=ids
            )
        except Exception as e:
            logger.error("Chroma 写入失败: doc_id=%s, error=%s", doc_id, e, exc_info=True)
            # 尝试回滚：删除可能已写入的部分数据
            try:
                await self.delete_by_doc_id(doc_id)
                logger.info("回滚成功: 已清理 doc_id=%s 的部分数据", doc_id)
            except Exception as rollback_err:
                logger.warning(
                    "回滚失败（需手动清理）: doc_id=%s, error=%s",
                    doc_id, rollback_err,
                )
            return {
                "success": False,
                "chunk_count": 0,
                "doc_id": doc_id,
                "message": f"上传失败: {str(e)}",
            }

        logger.info("上传成功: doc_id=%s, chunks=%d", doc_id, len(chunks))
        return {
            "success": True,
            "chunk_count": len(chunks),
            "doc_id": doc_id,
            "message": f"上传成功，共 {len(chunks)} 个语义块",
        }

    async def delete_by_doc_id(self, doc_id: str) -> int:
        """
        按文档 ID 删除 Chroma 中所有关联的向量数据

        通过 metadata 过滤 {doc_id: xxx} 找到所有分块并删除。

        Args:
            doc_id: 上传时生成的文档唯一标识

        Returns:
            int: 删除的分块数量（0 表示未找到）

        Note:
            使用 Chroma 的 where 过滤 + get + delete 三步操作
        """
        try:
            # 1. 查询该 doc_id 的所有分块
            result = await asyncio.to_thread(
                self.chroma.get, where={"doc_id": doc_id}
            )
            chunk_ids = result.get("ids", [])
            if not chunk_ids:
                logger.debug("delete_by_doc_id: doc_id=%s 无数据，跳过", doc_id)
                return 0

            # 2. 按 ID 删除
            await asyncio.to_thread(
                self.chroma.delete, ids=chunk_ids
            )
            logger.info("delete_by_doc_id: doc_id=%s 已删除 %d 个分块", doc_id, len(chunk_ids))
            return len(chunk_ids)

        except Exception as e:
            logger.error("delete_by_doc_id 失败: doc_id=%s, error=%s", doc_id, e, exc_info=True)
            raise
