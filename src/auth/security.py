"""
安全模块：密码哈希和 FastAPI 认证依赖注入

- 密码使用 bcrypt 哈希（直接使用 bcrypt 库，兼容 bcrypt 5.x）
- get_current_user 依赖注入从请求头解析 JWT 并查询用户
"""

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_async_session
from src.db.models import User
from src.auth.jwt_handler import decode_token

# HTTP Bearer 认证方案
# auto_error=False：不在 HTTPBearer 层直接抛异常，改为在 get_current_user 中
# 统一返回 401（而非 403），使前端 auto-refresh 机制能正常触发
bearer_scheme = HTTPBearer(auto_error=False)

# bcrypt 单条密码最大长度（72 字节）
_BCRYPT_MAX_LENGTH = 72


def hash_password(password: str) -> str:
    """
    对明文密码进行 bcrypt 哈希。

    bcrypt 限制密码最长为 72 字节，超长部分会被截断。
    """
    # 截断过长的密码（bcrypt 的限制）
    pwd_bytes = password.encode("utf-8")[:_BCRYPT_MAX_LENGTH]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与 bcrypt 哈希值是否匹配"""
    pwd_bytes = plain_password.encode("utf-8")[:_BCRYPT_MAX_LENGTH]
    return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    """
    FastAPI 依赖注入：验证 JWT 并从数据库加载当前用户。

    用法:
        @app.get("/protected")
        async def route(current_user: User = Depends(get_current_user)):
            ...

    Raises:
        HTTPException 401: token 无效、过期、缺失或用户不存在
        HTTPException 403: 账号已被禁用
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    token = credentials.credentials

    try:
        payload = decode_token(token)
    except Exception:
        raise credentials_exception

    # 仅接受 access_token
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请使用 access_token 访问",
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    # 从数据库加载用户
    result = await session.execute(
        select(User).where(User.id == int(user_id))
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )

    # 验证 token_version：改密码后旧 token 自动失效
    token_ver = payload.get("ver", 0)
    if token_ver != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="密码已修改，请重新登录",
        )

    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_async_session),
) -> User | None:
    """
    可选的认证依赖：解析成功返回用户，失败返回 None。
    用于同时支持匿名和登录用户的端点。
    """
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, session)
    except HTTPException:
        return None
