"""
对话 API 路由

POST /api/chat/               — 发送消息（非流式）
POST /api/chat/stream         — 发送消息（SSE 流式，含 Agent 事件）
GET  /api/chat/history/{sid}  — 获取会话历史
DELETE /api/chat/history/{sid} — 清空会话历史
GET  /api/chat/sessions       — 获取用户会话列表
"""

import hashlib
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.db.database import get_async_session
from src.db.models import User, ChatHistory
from src.auth.security import get_current_user
from src.agent.formatter import format_answer_output
import src.config as config

# ---- 日志 ----
logger = logging.getLogger("ChatAPI")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(_h)

router = APIRouter(prefix="/api/chat", tags=["对话"])


# AgentService 实例池（按 user_id 缓存，避免每次请求重新初始化 embedding/BM25/Chroma）
_agent_service_pool: dict = {}

def _get_agent_service(user_id: int = None):
    """获取缓存的 Agent 服务实例（支持用户隔离）。

    每个 user_id 对应一个长期存活的 AgentService，避免每次请求
    重新加载 embedding 模型、BM25 索引和 Chroma 全量文档。

    Args:
        user_id: 用户 ID，None 时使用默认配置
    """
    from src.agent.service import AgentService

    key = user_id if user_id is not None else "__default__"
    if key not in _agent_service_pool:
        logger.info("创建 AgentService 实例（user=%s），首次初始化包含 embedding/BM25/Chroma 加载", user_id)
        _agent_service_pool[key] = AgentService(user_id=user_id)
    return _agent_service_pool[key]


async def cleanup_agent_services():
    """关闭所有缓存的 AgentService 实例（应用关闭时调用）。"""
    for key, svc in list(_agent_service_pool.items()):
        try:
            await svc.close()
        except Exception:
            pass
    _agent_service_pool.clear()
    logger.info("所有 AgentService 实例已关闭")


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
        logger.debug("GET /sessions: user=%s 无会话记录", current_user.id)
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
        title = first_msg[:50] if first_msg else "新会话"

        session_list.append({
            "session_id": sid,
            "title": title,
            "last_active": last_active.isoformat() if last_active else None,
        })

    logger.debug("GET /sessions: user=%s 返回 %d 个会话", current_user.id, len(session_list))
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
    logger.debug("GET /history/%s: user=%s 返回 %d 条消息", session_id, current_user.id, len(messages))
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
    logger.info("DELETE /history/%s: user=%s 已清空", session_id, current_user.id)
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

    t0 = time.monotonic()
    logger.info("POST /chat: user=%s session=%s query=%s",
                 current_user.id, session_id, query[:80])

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

    # 调用 Agent 服务（实例池缓存，不可 close）
    agent_svc = _get_agent_service(user_id=current_user.id)
    try:
        answer = await agent_svc.ainvoke({"input": query}, session_config)
    except Exception as e:
        logger.error("POST /chat: Agent 调用失败 user=%s session=%s: %s",
                      current_user.id, session_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent 服务错误: {str(e)}")

    # 保存 AI 回答
    ai_msg = ChatHistory(
        user_id=current_user.id,
        session_id=session_id,
        role="assistant",
        content=answer,
    )
    db_session.add(ai_msg)
    await db_session.commit()

    elapsed = time.monotonic() - t0
    logger.info("POST /chat: 完成 user=%s session=%s 耗时=%.2fs answer_len=%d",
                 current_user.id, session_id, elapsed, len(answer))

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

    Agent 模式事件类型:
        event: token
        data: 文本片段

        event: tool_start
        data: {"tools": [{"name": "...", "args": {...}}]}

        event: tool_end
        data: {"tool": "...", "result_preview": "..."}

        event: summarize
        data: (空，表示对话历史已自动总结)

        event: session_end
        data: (空，表示会话结束总结已生成)

        event: done
        data: [DONE]

    - query: 用户查询
    - session_id: 会话 ID（不传则自动创建新会话）
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    t0 = time.monotonic()
    logger.info("POST /chat/stream: user=%s session=%s query=%s",
                 current_user.id, session_id, query[:80])

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

    agent_svc = _get_agent_service(user_id=current_user.id)

    async def event_generator():
        full_answer_parts = []
        event_stats = {"token": 0, "tool_start": 0, "tool_end": 0,
                       "summarize": 0, "session_end": 0, "error": 0}
        try:
            async for event in agent_svc.astream(
                {"input": query}, session_config
            ):
                event_type = event["type"]
                event_data = event["data"]
                event_stats[event_type] = event_stats.get(event_type, 0) + 1

                if event_type == "token":
                    full_answer_parts.append(event_data)
                    yield {"event": "token", "data": event_data}

                elif event_type == "tool_start":
                    yield {
                        "event": "tool_start",
                        "data": json.dumps(event_data, ensure_ascii=False),
                    }

                elif event_type == "tool_end":
                    yield {
                        "event": "tool_end",
                        "data": json.dumps(event_data, ensure_ascii=False),
                    }

                elif event_type == "summarize":
                    logger.info("SSE: 对话历史总结事件（session=%s）", session_id)
                    yield {"event": "summarize", "data": ""}

                elif event_type == "session_end":
                    logger.info("SSE: 会话结束总结事件（session=%s）", session_id)
                    yield {"event": "session_end", "data": ""}

                elif event_type == "thinking":
                    yield {"event": "thinking", "data": ""}

        except Exception as e:
            logger.error("SSE stream: 错误 user=%s session=%s: %s",
                          current_user.id, session_id, e, exc_info=True)
            event_stats["error"] += 1
            yield {"event": "error", "data": str(e)}
            return

        finally:
            # 流结束后保存 AI 回答到 MySQL
            answer = "".join(full_answer_parts)
            if answer:
                # 格式化输出后再保存
                formatted_answer = format_answer_output(answer)
                ai_msg = ChatHistory(
                    user_id=current_user.id,
                    session_id=session_id,
                    role="assistant",
                    content=formatted_answer,
                )
                db_session.add(ai_msg)
                await db_session.commit()

            # 注：agent_svc 由实例池管理，不在单次请求中关闭

            elapsed = time.monotonic() - t0
            logger.info("POST /chat/stream: 完成 user=%s session=%s 耗时=%.2fs "
                         "answer_len=%d events=%s",
                         current_user.id, session_id, elapsed,
                         len(answer), event_stats)

        yield {"event": "done", "data": "[DONE]"}

    return EventSourceResponse(event_generator())
