"""
JWT Token 处理模块

使用 PyJWT + cryptography 实现：
  - access_token（短期，30分钟）
  - refresh_token（长期，7天）
  - token 黑名单（Redis 实现，登出/刷新时失效旧 token）
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt

import src.config as config

# 时区
TZ = timezone(timedelta(hours=8))  # Asia/Shanghai


def create_access_token(user_id: int, username: str, token_version: int = 0) -> str:
    """
    生成短期 access_token。

    payload:
        - sub: user_id (str)
        - username: 用户名
        - jti: token 唯一 ID（用于黑名单）
        - type: "access"
        - ver: token_version（改密码时递增，使旧 token 失效）
        - iat / exp: 签发时间 / 过期时间
    """
    now = datetime.now(TZ)
    payload = {
        "sub": str(user_id),
        "username": username,
        "jti": uuid.uuid4().hex,
        "type": "access",
        "ver": token_version,
        "iat": now,
        "exp": now + timedelta(minutes=config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def create_refresh_token(user_id: int, username: str, token_version: int = 0) -> str:
    """
    生成长期 refresh_token。

    payload:
        - sub: user_id (str)
        - type: "refresh"
        - jti: token 唯一 ID
        - ver: token_version（改密码时递增，使旧 token 失效）
        - iat / exp: 签发时间 / 过期时间
    """
    now = datetime.now(TZ)
    payload = {
        "sub": str(user_id),
        "username": username,
        "jti": uuid.uuid4().hex,
        "type": "refresh",
        "ver": token_version,
        "iat": now,
        "exp": now + timedelta(days=config.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    解码并验证 JWT token。

    Returns:
        payload 字典

    Raises:
        jwt.ExpiredSignatureError: token 已过期
        jwt.InvalidTokenError: token 无效
    """
    return jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[config.JWT_ALGORITHM])


def get_token_expiry(token_type: str = "access") -> timedelta:
    """获取 token 过期时长"""
    if token_type == "access":
        return timedelta(minutes=config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    else:
        return timedelta(days=config.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
