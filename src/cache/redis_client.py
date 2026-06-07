"""
Redis 缓存客户端模块

提供：
  - 异步 Redis 连接管理
  - JWT token 黑名单（登出/刷新时加入）
  - 查询结果缓存
  - API 频率限制（滑动窗口）
"""

import redis.asyncio as aioredis
from redis.asyncio import Redis
import src.config as config

# 全局 Redis 连接实例
_redis: Redis | None = None


async def get_redis() -> Redis:
    """
    获取 Redis 连接（懒加载单例）。

    用法:
        redis = await get_redis()
        await redis.get("key")
    """
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            f"redis://{config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}",
            password=config.REDIS_PASSWORD,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis():
    """关闭 Redis 连接（应用关闭时调用）。"""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None


# ==================== JWT 黑名单 ====================

async def add_to_blacklist(jti: str, ttl_seconds: int) -> None:
    """
    将 token 的唯一 ID 加入黑名单（登出、刷新旧 token 时调用）。

    Args:
        jti: token 的唯一标识
        ttl_seconds: 黑名单有效期（应与 token 剩余有效时间一致）
    """
    redis = await get_redis()
    await redis.setex(f"jwt:blacklist:{jti}", ttl_seconds, "1")


async def is_blacklisted(jti: str) -> bool:
    """检查 token 是否在黑名单中。"""
    redis = await get_redis()
    return await redis.exists(f"jwt:blacklist:{jti}") > 0


# ==================== 查询缓存 ====================

async def get_cached_query(user_id: int, query_md5: str) -> str | None:
    """获取缓存的查询结果。"""
    redis = await get_redis()
    return await redis.get(f"query_cache:{user_id}:{query_md5}")


async def set_cached_query(user_id: int, query_md5: str, answer: str, ttl: int = 1800) -> None:
    """
    缓存查询结果（默认 30 分钟）。

    Args:
        ttl: 缓存有效期（秒）
    """
    redis = await get_redis()
    await redis.setex(f"query_cache:{user_id}:{query_md5}", ttl, answer)


# ==================== 频率限制 ====================

async def check_rate_limit(user_id: int, endpoint: str, max_requests: int = 30, window: int = 60) -> bool:
    """
    滑动窗口频率限制。

    Args:
        user_id: 用户 ID
        endpoint: API 端点标识
        max_requests: 窗口内最大请求数
        window: 时间窗口（秒）

    Returns:
        True: 未超限
        False: 已超限
    """
    redis = await get_redis()
    key = f"rate_limit:{user_id}:{endpoint}"
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window)
    return current <= max_requests
