"""
认证相关的 Pydantic 数据模型（请求/响应 schema）
"""

from pydantic import BaseModel, Field, field_validator
import re


# ==================== 请求模型 ====================

class UserRegisterRequest(BaseModel):
    """用户注册请求"""
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码")
    email: str | None = Field(None, max_length=100, description="邮箱（可选）")

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """用户名只允许字母、数字、下划线、中文"""
        if not re.match(r'^[\w一-鿿]+$', v):
            raise ValueError("用户名只能包含字母、数字、下划线和中文")
        return v.strip()


class UserLoginRequest(BaseModel):
    """用户登录请求"""
    username: str = Field(..., min_length=1, description="用户名")
    password: str = Field(..., min_length=1, description="密码")


class TokenRefreshRequest(BaseModel):
    """刷新 token 请求"""
    refresh_token: str = Field(..., description="refresh_token")


class LogoutRequest(BaseModel):
    """登出请求（可选传入 refresh_token 以失效长期 token）"""
    refresh_token: str | None = Field(None, description="refresh_token（可选，用于同时失效）")


class PasswordChangeRequest(BaseModel):
    """修改密码请求"""
    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., min_length=6, max_length=128, description="新密码")


# ==================== 响应模型 ====================

class TokenResponse(BaseModel):
    """登录/刷新成功响应"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """用户公开信息"""
    id: int
    username: str
    email: str | None = None
    is_active: bool
    created_at: str | None = None

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    """通用消息响应"""
    message: str
