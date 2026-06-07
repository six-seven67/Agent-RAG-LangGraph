"""
MySQL 对话历史存储模块

实现 LangChain 的 BaseChatMessageHistory 接口，
将对话历史持久化到 MySQL，支持用户隔离。

与 file_history_store.py 接口兼容，可在配置中选择使用哪种存储。
"""

import json
import os
from typing import Sequence

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import AsyncSessionLocal
from src.db.models import ChatHistory


class MySQLChatMessageHistory(BaseChatMessageHistory):
    """
    基于 MySQL 的对话历史存储，实现 LangChain BaseChatMessageHistory 接口。

    每个实例绑定一个 (user_id, session_id) 组合，保证用户隔离。

    Usage:
        history = MySQLChatMessageHistory(user_id=1, session_id="abc-123")
        history.add_messages([HumanMessage("你好")])
        messages = history.messages  # 返回历史消息列表
    """

    def __init__(self, user_id: int, session_id: str):
        self.user_id = user_id
        self.session_id = session_id

    async def _get_session(self) -> AsyncSession:
        """获取异步数据库 session。"""
        return AsyncSessionLocal()

    @property
    def messages(self) -> list[BaseMessage]:
        """
        同步读取消息（LangChain RunnableWithMessageHistory 要求同步接口）。

        使用内部事件循环在同步上下文中执行异步查询。
        """
        import asyncio

        async def _fetch():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(ChatHistory)
                    .where(ChatHistory.user_id == self.user_id)
                    .where(ChatHistory.session_id == self.session_id)
                    .order_by(ChatHistory.created_at.asc())
                )
                rows = result.scalars().all()
                messages_data = [
                    {"type": row.role, "data": {"content": row.content}}
                    for row in rows
                ]
                # 转换为 LangChain 格式
                converted = []
                for item in messages_data:
                    if item["type"] == "user":
                        from langchain_core.messages import HumanMessage
                        converted.append(HumanMessage(content=item["data"]["content"]))
                    elif item["type"] == "assistant":
                        from langchain_core.messages import AIMessage
                        converted.append(AIMessage(content=item["data"]["content"]))
                return converted

        # 处理同步调用（兼容 LangChain 的同步链）
        try:
            loop = asyncio.get_running_loop()
            # 如果已经在事件循环中运行，使用 nest_asyncio 或新建 loop
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _fetch())
                return future.result(timeout=10)
        except RuntimeError:
            # 没有运行中的事件循环，直接创建
            return asyncio.run(_fetch())

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        """
        同步添加消息（LangChain 的 RunnableWithMessageHistory 调用此方法）。

        Args:
            messages: 完整的消息序列（LangChain 传入完整的对话历史）
        """
        import asyncio

        async def _persist():
            async with AsyncSessionLocal() as session:
                # 先删除该会话的旧消息（LangChain 传入完整历史，所以替换式更新）
                await session.execute(
                    delete(ChatHistory)
                    .where(ChatHistory.user_id == self.user_id)
                    .where(ChatHistory.session_id == self.session_id)
                )

                # 批量插入新消息
                for msg in messages:
                    role = "user" if msg.type == "human" else "assistant"
                    record = ChatHistory(
                        user_id=self.user_id,
                        session_id=self.session_id,
                        role=role,
                        content=msg.content,
                    )
                    session.add(record)

                await session.commit()

        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _persist())
                future.result(timeout=10)
        except RuntimeError:
            asyncio.run(_persist())

    def clear(self) -> None:
        """清空该会话的历史消息。"""
        import asyncio

        async def _clear():
            async with AsyncSessionLocal() as session:
                await session.execute(
                    delete(ChatHistory)
                    .where(ChatHistory.user_id == self.user_id)
                    .where(ChatHistory.session_id == self.session_id)
                )
                await session.commit()

        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _clear())
                future.result(timeout=10)
        except RuntimeError:
            asyncio.run(_clear())


# ==================== 历史存储工厂函数 ====================

# 全局存储模式标志
STORAGE_BACKEND = "mysql"  # "mysql" | "file"


def get_history(session_id: str, user_id: int | None = None):
    """
    获取对话历史存储实例。

    - 当 STORAGE_BACKEND="mysql" 且 user_id 不为 None 时，使用 MySQL 存储
    - 否则回退到文件存储（向后兼容）

    Args:
        session_id: 会话 ID
        user_id: 用户 ID（MySQL 模式必需）

    Returns:
        BaseChatMessageHistory 实例
    """
    if STORAGE_BACKEND == "mysql" and user_id is not None:
        return MySQLChatMessageHistory(user_id=user_id, session_id=session_id)
    else:
        from src.file_history_store import FileChatMessageHistory
        return FileChatMessageHistory(session_id)


def load_history_for_ui(session_id: str, user_id: int | None = None) -> list[dict]:
    """
    加载会话历史，返回 UI 兼容格式。

    Args:
        session_id: 会话 ID
        user_id: 用户 ID（MySQL 模式必需）

    Returns:
        [{"role": "user"|"assistant", "content": "..."}, ...]
    """
    if STORAGE_BACKEND == "mysql" and user_id is not None:
        import asyncio

        async def _load():
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(ChatHistory)
                    .where(ChatHistory.user_id == user_id)
                    .where(ChatHistory.session_id == session_id)
                    .order_by(ChatHistory.created_at.asc())
                )
                return [
                    {"role": row.role, "content": row.content}
                    for row in result.scalars().all()
                ]

        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _load())
                return future.result(timeout=10)
        except RuntimeError:
            return asyncio.run(_load())
    else:
        from src.file_history_store import load_history_for_ui as file_load
        return file_load(session_id)
