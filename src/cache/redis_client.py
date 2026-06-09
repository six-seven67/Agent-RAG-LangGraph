"""
Redis 缓存客户端模块

提供：
  - 异步 Redis 连接管理
  - JWT token 黑名单（登出/刷新时加入）
  - 查询结果缓存
  - API 频率限制（滑动窗口）
"""

import logging

import redis.asyncio as aioredis
from redis.asyncio import Redis
import src.config as config

logger = logging.getLogger("RedisClient")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(_h)

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
        logger.info("正在连接 Redis（%s:%s）...", config.REDIS_HOST, config.REDIS_PORT)
        _redis = aioredis.from_url(
            f"redis://{config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}",
            password=config.REDIS_PASSWORD,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def ping_redis() -> bool:
    """测试 Redis 连接是否真正可用。

    aioredis.from_url() 是延迟建连的，只创建连接池不验证。
    通过 ping() 真正测试网络连通性。

    Returns:
        True: 连接正常
        False: 连接失败
    """
    try:
        redis = await get_redis()
        result = await redis.ping()
        return result is True
    except Exception as e:
        logger.error("Redis ping 失败（%s:%s）: %s",
                     config.REDIS_HOST, config.REDIS_PORT, e)
        return False


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
    try:
        redis = await get_redis()
        await redis.setex(f"jwt:blacklist:{jti}", ttl_seconds, "1")
    except Exception as e:
        logger.error("黑名单写入失败（jti=%s）: %s", jti[:10], e)


async def is_blacklisted(jti: str) -> bool:
    """检查 token 是否在黑名单中。

    Redis 不可用时降级为 False（不阻止任何请求），避免系统完全不可用。
    """
    try:
        redis = await get_redis()
        return await redis.exists(f"jwt:blacklist:{jti}") > 0
    except Exception as e:
        logger.warning("黑名单检查失败（jti=%s），降级放行: %s", jti[:10], e)
        return False


# ==================== 查询缓存 ====================

async def get_cached_query(user_id: int, query_md5: str) -> str | None:
    """获取缓存的查询结果。Redis 不可用时返回 None（缓存穿透）。"""
    try:
        redis = await get_redis()
        return await redis.get(f"query_cache:{user_id}:{query_md5}")
    except Exception as e:
        logger.debug("缓存读取失败（user=%s），穿透: %s", user_id, e)
        return None


async def set_cached_query(user_id: int, query_md5: str, answer: str, ttl: int = 1800) -> None:
    """缓存查询结果（默认 30 分钟）。Redis 不可用时静默跳过。"""
    try:
        redis = await get_redis()
        await redis.setex(f"query_cache:{user_id}:{query_md5}", ttl, answer)
    except Exception as e:
        logger.debug("缓存写入失败（user=%s），跳过: %s", user_id, e)


# ==================== 频率限制 ====================

async def check_rate_limit(user_id: int, endpoint: str, max_requests: int = 30, window: int = 60) -> bool:
    """
    滑动窗口频率限制。

    Redis 不可用时降级为 True（不限制），避免系统完全不可用。

    Args:
        user_id: 用户 ID
        endpoint: API 端点标识
        max_requests: 窗口内最大请求数
        window: 时间窗口（秒）

    Returns:
        True: 未超限
        False: 已超限
    """
    try:
        redis = await get_redis()
        key = f"rate_limit:{user_id}:{endpoint}"
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, window)
        return current <= max_requests
    except Exception as e:
        logger.warning("频率限制检查失败（user=%s, endpoint=%s），降级放行: %s",
                      user_id, endpoint, e)
        return True
