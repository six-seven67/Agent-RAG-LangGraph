"""对话历史存储 — 文件后端 + MySQL 后端（可插拔）。

扩展：新增存储后端（如 Redis、PostgreSQL）在此添加新文件。
"""

from src.storage.file_store import FileChatMessageHistory, get_history, load_history_for_ui
from src.storage.mysql_store import MySQLChatMessageHistory

__all__ = [
    "FileChatMessageHistory",
    "get_history",
    "load_history_for_ui",
    "MySQLChatMessageHistory",
]
