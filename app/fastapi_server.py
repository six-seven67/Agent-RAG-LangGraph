"""
FastAPI 主服务入口

启动方式:
    # 开发模式
    uvicorn app.fastapi_server:app --reload --host 0.0.0.0 --port 8000

    # 生产模式
    uvicorn app.fastapi_server:app --host 0.0.0.0 --port 8000 --workers 4

OpenAPI 文档:
    http://localhost:8000/docs          # Swagger UI
    http://localhost:8000/redoc         # ReDoc
"""

import sys
import os

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.db.database import init_db, engine
from src.cache.redis_client import get_redis, close_redis

# 导入 API 路由
from src.api.auth import router as auth_router
from src.api.chat import router as chat_router
from src.api.knowledge import router as knowledge_router
from src.api.user import router as user_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 生命周期管理：
    - 启动时：初始化数据库表、连接 Redis
    - 关闭时：断开 Redis、释放数据库连接池
    """
    # ===== 启动 =====
    print("[FastAPI] 正在初始化数据库表...")
    await init_db()
    print("[FastAPI] 数据库表初始化完成")

    print("[FastAPI] 正在连接 Redis...")
    await get_redis()
    print("[FastAPI] Redis 连接成功")

    yield  # 应用运行中

    # ===== 关闭 =====
    print("[FastAPI] 正在关闭 Redis 连接...")
    await close_redis()

    print("[FastAPI] 正在关闭数据库引擎...")
    await engine.dispose()

    print("[FastAPI] 应用已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="RAG 智能客服系统",
    description="基于检索增强生成的智能客服 API，支持用户认证、知识库管理和流式对话",
    version="2.0.0",
    lifespan=lifespan,
)

# ==================== CORS 中间件 ====================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== JWT 黑名单中间件 ====================
@app.middleware("http")
async def jwt_blacklist_middleware(request: Request, call_next):
    """
    检查请求中的 JWT token 是否在黑名单中。
    如果已登出（token 在黑名单中），返回 401。
    """
    from src.cache.redis_client import is_blacklisted
    from src.auth.jwt_handler import decode_token

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            payload = decode_token(token)
            jti = payload.get("jti")
            if jti and await is_blacklisted(jti):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Token 已失效（已登出）"},
                )
        except Exception:
            pass  # token 无效，由 get_current_user 依赖处理

    response = await call_next(request)
    return response


# ==================== 健康检查 ====================
@app.get("/health", tags=["系统"])
async def health_check():
    """健康检查端点"""
    return {"status": "ok", "service": "RAG 智能客服系统", "version": "2.0.0"}


# ==================== 注册路由 ====================
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(knowledge_router)
app.include_router(user_router)


# ==================== 调试入口 ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.fastapi_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
