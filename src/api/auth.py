"""
认证 API 路由

POST /api/auth/register — 注册
POST /api/auth/login    — 登录
POST /api/auth/refresh  — 刷新 token
POST /api/auth/logout   — 登出
"""

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_async_session
from src.db.models import User
from src.auth.security import (
    hash_password,
    verify_password,
    get_current_user,
)
from src.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_expiry,
)
from src.auth.schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenRefreshRequest,
    LogoutRequest,
    PasswordChangeRequest,
    TokenResponse,
    UserResponse,
    MessageResponse,
)
from src.cache.redis_client import add_to_blacklist, is_blacklisted, check_and_blacklist

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    req: UserRegisterRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """用户注册：创建账号并返回 token"""
    # 检查用户名是否已存在
    result = await session.execute(
        select(User).where(User.username == req.username)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )

    # 创建用户
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        email=req.email,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    # 生成 token
    access_token = create_access_token(user.id, user.username, user.token_version)
    refresh_token = create_refresh_token(user.id, user.username, user.token_version)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    req: UserLoginRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """用户登录：验证凭据并返回 token"""
    # 查找用户
    result = await session.execute(
        select(User).where(User.username == req.username)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )

    # 生成 token
    access_token = create_access_token(user.id, user.username, user.token_version)
    refresh_token = create_refresh_token(user.id, user.username, user.token_version)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    req: TokenRefreshRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """刷新 access_token（使用 refresh_token 换取新的一对 token）"""
    try:
        payload = decode_token(req.refresh_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="refresh_token 无效或已过期",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请使用 refresh_token 刷新",
        )

    # 原子检查并加入黑名单（防止并发重放攻击）
    jti = payload.get("jti")
    if jti:
        remaining = int((datetime.fromtimestamp(payload["exp"], tz=timezone.utc) -
                         datetime.now(timezone.utc)).total_seconds())
        if remaining > 0:
            if not await check_and_blacklist(jti, remaining):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="此 refresh_token 已被使用（检测到并发刷新）",
                )

    user_id = int(payload["sub"])
    username = payload["username"]

    # 验证用户仍存在且活跃
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号不存在或已禁用",
        )

    # 签发新 token
    new_access = create_access_token(user.id, user.username, user.token_version)
    new_refresh = create_refresh_token(user.id, user.username, user.token_version)

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    req: LogoutRequest | None = None,
    current_user: User = Depends(get_current_user),
):
    """登出：将 access_token 和 refresh_token（如提供）加入 Redis 黑名单。

    客户端需配合清除本地 token（access_token + refresh_token）。
    """
    # 1. 黑名单当前 access_token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header[7:]
        try:
            payload = decode_token(raw_token)
            jti = payload.get("jti")
            if jti:
                # 计算 token 剩余有效时间作为黑名单 TTL
                remaining = int((datetime.fromtimestamp(payload["exp"], tz=timezone.utc) -
                                 datetime.now(timezone.utc)).total_seconds())
                if remaining > 0:
                    await add_to_blacklist(jti, remaining)
        except Exception:
            pass  # token 解析失败不影响登出流程

    # 2. 黑名单 refresh_token（如客户端提供）
    if req and req.refresh_token:
        try:
            payload = decode_token(req.refresh_token)
            if payload.get("type") == "refresh":
                jti = payload.get("jti")
                if jti:
                    remaining = int((datetime.fromtimestamp(payload["exp"], tz=timezone.utc) -
                                     datetime.now(timezone.utc)).total_seconds())
                    if remaining > 0:
                        await add_to_blacklist(jti, remaining)
        except Exception:
            pass  # refresh_token 解析失败不影响登出流程

    return MessageResponse(message="已登出，请清除本地 token")


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
):
    """获取当前登录用户信息"""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        is_active=current_user.is_active,
        created_at=current_user.created_at.strftime("%Y-%m-%d %H:%M:%S") if current_user.created_at else None,
    )
