"""Agent 工具 — 一个工具一个文件，新增工具只需在此添加 .py 文件并在 __init__.py 重导出。
"""

from src.agent.tools.search_kb import make_search_knowledge_base
from src.agent.tools.web_search import make_web_search

__all__ = [
    "make_search_knowledge_base",
    "make_web_search",
]
