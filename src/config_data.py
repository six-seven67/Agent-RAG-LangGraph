import os
from dotenv import load_dotenv

load_dotenv()

# ===== 路径配置 =====
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
md5_path = os.path.join(_BASE_DIR, "md5.text")
chroma_path = os.path.join(_BASE_DIR, "chroma.db")
chat_history_path = os.path.join(_BASE_DIR, "chat_history")

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
