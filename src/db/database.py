"""
异步数据库连接管理模块

使用 SQLAlchemy 2.0 async engine + aiomysql 驱动，
提供异步 session 工厂和 FastAPI 依赖注入。
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import src.config as config


# 构建 MySQL 异步连接 URL
DATABASE_URL = (
    f"mysql+aiomysql://{config.MYSQL_USER}:{config.MYSQL_PASSWORD}"
    f"@{config.MYSQL_HOST}:{config.MYSQL_PORT}/{config.MYSQL_DATABASE}"
    f"?charset=utf8mb4"
)

# 异步引擎（echo=False 生产环境关闭 SQL 日志）
engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)

# 异步 session 工厂
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass


async def get_async_session() -> AsyncSession:
    """
    FastAPI 依赖注入：获取异步数据库 session。

    用法:
        @app.get("/")
        async def route(session: AsyncSession = Depends(get_async_session)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """初始化数据库表（开发环境使用，生产环境请用 Alembic 迁移）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
