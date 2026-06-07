"""
对话 API 路由

POST /api/chat/               — 发送消息（非流式）
POST /api/chat/stream         — 发送消息（SSE 流式）
GET  /api/chat/history/{sid}  — 获取会话历史
DELETE /api/chat/history/{sid} — 清空会话历史
GET  /api/chat/sessions       — 获取用户会话列表
"""

import hashlib
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.db.database import get_async_session
from src.db.models import User, ChatHistory
from src.auth.security import get_current_user
from src import config_data as config
from src.cache.redis_client import get_cached_query, set_cached_query

router = APIRouter(prefix="/api/chat", tags=["对话"])


def _get_rag_service(user_id: int = None):
    """懒加载 RAG 服务实例（支持用户隔离）。

    Args:
        user_id: 用户 ID，None 时使用默认 collection
    """
    from src.rag_async import AsyncRagService
    return AsyncRagService(user_id=user_id)


def _query_md5(query: str) -> str:
    return hashlib.md5(query.encode()).hexdigest()


# ==================== 获取会话列表 ====================

@router.get("/sessions")
async def list_sessions(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    获取当前用户的所有会话列表（按最近活动排序）。

    每个会话返回其第一条用户消息作为会话标题，便于前端展示。
    """
    # 子查询：每个会话的第一条用户消息（按时间升序取最早的那条）
    from sqlalchemy import and_

    # 1. 获取所有会话的 session_id 和最近活动时间
    result = await session.execute(
        select(
            ChatHistory.session_id,
            func.max(ChatHistory.created_at).label("last_active")
        )
        .where(ChatHistory.user_id == current_user.id)
        .group_by(ChatHistory.session_id)
        .order_by(func.max(ChatHistory.created_at).desc())
        .limit(50)
    )
    session_rows = [(row[0], row[1]) for row in result.all()]

    if not session_rows:
        return {"sessions": [], "total": 0}

    # 2. 为每个会话查询第一条用户消息作为标题
    session_list = []
    for sid, last_active in session_rows:
        first_msg_result = await session.execute(
            select(ChatHistory.content)
            .where(
                and_(
                    ChatHistory.user_id == current_user.id,
                    ChatHistory.session_id == sid,
                    ChatHistory.role == "user",
                )
            )
            .order_by(ChatHistory.created_at.asc())
            .limit(1)
        )
        first_msg = first_msg_result.scalar_one_or_none()
        title = first_msg[:50] if first_msg else "新会话"  # 截断过长标题

        session_list.append({
            "session_id": sid,
            "title": title,
            "last_active": last_active.isoformat() if last_active else None,
        })

    return {"sessions": session_list, "total": len(session_list)}


# ==================== 获取历史 ====================

@router.get("/history/{session_id}")
async def get_history(
    session_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """获取指定会话的对话历史（仅限当前用户）。"""
    result = await session.execute(
        select(ChatHistory)
        .where(ChatHistory.user_id == current_user.id)
        .where(ChatHistory.session_id == session_id)
        .order_by(ChatHistory.created_at.asc())
    )
    messages = [
        {"role": msg.role, "content": msg.content, "created_at": msg.created_at.isoformat()}
        for msg in result.scalars().all()
    ]
    return {"session_id": session_id, "messages": messages, "total": len(messages)}


@router.delete("/history/{session_id}")
async def clear_history(
    session_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """清空指定会话的对话历史（仅限当前用户）。"""
    await session.execute(
        delete(ChatHistory)
        .where(ChatHistory.user_id == current_user.id)
        .where(ChatHistory.session_id == session_id)
    )
    await session.commit()
    return {"message": f"会话 {session_id} 已清空"}


# ==================== 发送消息（非流式）====================

@router.post("/")
async def chat(
    query: str,
    session_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    发送消息并获取 AI 回答（非流式，返回完整结果）。

    - query: 用户查询
    - session_id: 会话 ID（不传则自动创建新会话）
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    session_config = config.build_session_config(session_id, user_id=current_user.id)

    # 保存用户消息到 MySQL
    user_msg = ChatHistory(
        user_id=current_user.id,
        session_id=session_id,
        role="user",
        content=query,
    )
    db_session.add(user_msg)
    await db_session.commit()

    # 调用 RAG 服务（用户隔离）
    rag_svc = _get_rag_service(user_id=current_user.id)
    answer = await rag_svc.ainvoke({"input": query}, session_config)

    # 保存 AI 回答
    ai_msg = ChatHistory(
        user_id=current_user.id,
        session_id=session_id,
        role="assistant",
        content=answer,
    )
    db_session.add(ai_msg)
    await db_session.commit()

    return {
        "session_id": session_id,
        "query": query,
        "answer": answer,
    }


# ==================== 发送消息（SSE 流式）====================

@router.post("/stream")
async def chat_stream(
    query: str,
    session_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    发送消息并获取流式 AI 回答（Server-Sent Events）。

    事件格式:
        data: {"token": "文本片段"}
        data: [DONE]

    - query: 用户查询
    - session_id: 会话 ID（不传则自动创建新会话）
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    session_config = config.build_session_config(session_id, user_id=current_user.id)

    # 保存用户消息
    user_msg = ChatHistory(
        user_id=current_user.id,
        session_id=session_id,
        role="user",
        content=query,
    )
    db_session.add(user_msg)
    await db_session.commit()

    rag_svc = _get_rag_service(user_id=current_user.id)

    async def event_generator():
        full_answer = []
        try:
            async for chunk in rag_svc.astream({"input": query}, session_config):
                full_answer.append(chunk)
                yield {"event": "token", "data": chunk}
        except Exception as e:
            yield {"event": "error", "data": str(e)}
            return
        finally:
            # 流结束后保存 AI 回答
            answer = "".join(full_answer)
            if answer:
                ai_msg = ChatHistory(
                    user_id=current_user.id,
                    session_id=session_id,
                    role="assistant",
                    content=answer,
                )
                db_session.add(ai_msg)
                await db_session.commit()

        yield {"event": "done", "data": "[DONE]"}

    return EventSourceResponse(event_generator())
