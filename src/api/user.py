"""
用户 API 路由

GET  /api/user/profile   — 获取个人信息
PUT  /api/user/profile   — 更新个人信息
PUT  /api/user/password  — 修改密码
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_async_session
from src.db.models import User
from src.auth.security import get_current_user, hash_password, verify_password
from src.auth.schemas import UserResponse, PasswordChangeRequest, MessageResponse

router = APIRouter(prefix="/api/user", tags=["用户"])


@router.get("/profile", response_model=UserResponse)
async def get_profile(
    current_user: User = Depends(get_current_user),
):
    """获取当前登录用户的个人信息。"""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        is_active=current_user.is_active,
        created_at=current_user.created_at.strftime("%Y-%m-%d %H:%M:%S") if current_user.created_at else None,
    )


@router.put("/profile")
async def update_profile(
    email: str | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """更新个人信息（当前仅支持修改邮箱）。"""
    if email is not None:
        current_user.email = email
        await session.commit()
        await session.refresh(current_user)
    return {"message": "更新成功", "email": current_user.email}


@router.put("/password", response_model=MessageResponse)
async def change_password(
    req: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """修改登录密码（需验证旧密码）。"""
    # 验证旧密码
    if not verify_password(req.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码不正确",
        )

    # 更新为新密码
    current_user.password_hash = hash_password(req.new_password)
    await session.commit()

    return MessageResponse(message="密码修改成功")
