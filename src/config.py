import os
from dotenv import load_dotenv

load_dotenv()

# ===== 路径配置 =====
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BASE_DIR, "data")
md5_path = os.path.join(_DATA_DIR, "md5.text")
chroma_path = os.path.join(_DATA_DIR, "chroma")
chat_history_path = os.path.join(_DATA_DIR, "chat_history")

collection_name = "rag"
collection_prefix = "rag_user"  # 用户隔离：每个用户的 collection 名为 rag_user_{user_id}

# spliter
chunk_size = 1000
chunk_overlap = 100
separators = ["\n\n", "\n", ".", "!", "?", "。", "，", "；", " ", ""]
max_split_char_number = 1000

# retriever
retrieval_top_k = 20

# hybrid search (混合检索)
hybrid_vector_k = 20
hybrid_bm25_k = 20
hybrid_fusion_k = 60
hybrid_top_k = 20

# reranker
reranker_model_name = "gte-rerank"
reranker_top_n = 3

# query rewrite (查询改写)
query_rewrite_enabled = True
query_rewrite_min_length = 15
query_rewrite_model_name = "qwen3-max"

# embedding & chat
embedding_model_name = "text-embedding-v4"
chat_model_name = "qwen3-max"

# ===== Agent 后端选择（v3.2.0）=====
# "custom" = 混合架构 StateGraph（classify → summarize → agent ⇄ tools）
# "legacy" = langchain.agents.create_agent（向后兼容）
agent_backend = os.getenv("AGENT_BACKEND", "custom").lower()

# ===== MySQL 数据库配置 =====
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "rag_system")

# ===== Redis 配置 =====
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# ===== JWT 配置 =====
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-to-a-random-secret")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))


# ===== Agent 对话总结（v3.2.0: 轮次触发）=====
# 触发总结的对话轮数阈值（每个用户消息 = 1 轮）
agent_summary_trigger_rounds = int(os.getenv("AGENT_SUMMARY_TRIGGER_ROUNDS", "6"))
# 两次总结之间的最小轮数间隔（避免每轮重复总结）
agent_summary_min_interval_rounds = int(os.getenv("AGENT_SUMMARY_MIN_INTERVAL_ROUNDS", "3"))
# 保留最近的消息条数（不被压缩）
agent_summary_keep_recent = int(os.getenv("AGENT_SUMMARY_KEEP_RECENT", "6"))
# 摘要最大字符数
agent_summary_max_chars = int(os.getenv("AGENT_SUMMARY_MAX_CHARS", "200"))

# ===== Agent 意图分类（classify_intent 规则匹配）=====
# 是否启用规则匹配快速路由（关闭则所有请求走 agent LLM 决策）
agent_classify_enabled = os.getenv("AGENT_CLASSIFY_ENABLED", "true").lower() == "true"

# ===== Web Search =====
web_search_enabled = os.getenv("WEB_SEARCH_ENABLED", "true").lower() == "true"
# TAVILY_API_KEY 直接在 os.getenv 中读取，不在此暴露默认值


def build_session_config(session_id: str, user_id: int = None) -> dict:
    """构建 LangChain RunnableWithMessageHistory 所需的会话配置。

    Args:
        session_id: 会话唯一标识
        user_id: 用户 ID（用于用户隔离，None 时向后兼容）
    """
    config = {
        "configurable": {
            "session_id": session_id,
        }
    }
    if user_id is not None:
        config["configurable"]["user_id"] = user_id
    return config


def get_user_collection_name(user_id: int) -> str:
    """获取用户隔离的 Chroma collection 名称。"""
    return f"{collection_prefix}_{user_id}"
