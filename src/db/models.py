"""
SQLAlchemy ORM 模型定义

表结构：
  - users: 用户账号表
  - chat_history: 对话历史表（用户隔离）
  - knowledge_docs: 知识库文档元数据表（用户隔离）
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    Enum as SAEnum, ForeignKey, Index,
)
from sqlalchemy.orm import relationship
from src.db.database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关系
    chat_histories = relationship("ChatHistory", back_populates="user", cascade="all, delete-orphan")
    knowledge_docs = relationship("KnowledgeDoc", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username})>"


class ChatHistory(Base):
    """对话历史表（用户隔离核心：通过 user_id 关联）"""
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(36), nullable=False, index=True)
    role = Column(SAEnum("user", "assistant", name="message_role"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    # 联合索引加速「按用户+会话查询历史」
    __table_args__ = (
        Index("idx_user_session", "user_id", "session_id"),
    )

    # 关系
    user = relationship("User", back_populates="chat_histories")

    def __repr__(self):
        return f"<ChatHistory(id={self.id}, user_id={self.user_id}, session_id={self.session_id})>"


class KnowledgeDoc(Base):
    """知识库文档元数据表（用户隔离核心：每个用户的文档独立记录）"""
    __tablename__ = "knowledge_docs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(255), nullable=False)
    md5_hash = Column(String(32), nullable=False)
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

    # 用户级去重索引
    __table_args__ = (
        Index("idx_user_md5", "user_id", "md5_hash"),
    )

    # 关系
    user = relationship("User", back_populates="knowledge_docs")

    def __repr__(self):
        return f"<KnowledgeDoc(id={self.id}, user_id={self.user_id}, filename={self.filename})>"
