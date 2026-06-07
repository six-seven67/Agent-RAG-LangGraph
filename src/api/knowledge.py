"""
知识库 API 路由

POST   /api/knowledge/upload        — 上传文档
GET    /api/knowledge/documents     — 获取文档列表
DELETE /api/knowledge/documents/{id} — 删除文档
"""

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_async_session
from src.db.models import User, KnowledgeDoc
from src.auth.security import get_current_user
from src.knowledge import KnowledgeBaseService, get_string_md5

router = APIRouter(prefix="/api/knowledge", tags=["知识库"])


def _get_kb_service(user_id: int) -> KnowledgeBaseService:
    """
    获取用户隔离的知识库服务实例。

    每个用户使用独立的 Chroma collection（物理隔离）。
    """
    import src.config as config
    collection_name = config.get_user_collection_name(user_id)
    return KnowledgeBaseService(collection_name=collection_name)


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(..., description="TXT 文件"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    上传 TXT 文档到用户的知识库。

    流程：
    1. 读取文件内容
    2. 计算 MD5 并检查用户级去重（MySQL + Chroma 双重校验）
    3. 语义分块 + 写入用户专属 Chroma collection
    4. 记录到 knowledge_docs 表
    """
    # 仅接受 .txt 文件
    if not file.filename.lower().endswith(".txt"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 TXT 格式文件",
        )

    # 读取文件内容
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件编码错误，请使用 UTF-8 编码",
        )

    # 计算 MD5
    md5_str = get_string_md5(text)

    # 检查用户级去重
    result = await session.execute(
        select(KnowledgeDoc).where(
            KnowledgeDoc.user_id == current_user.id,
            KnowledgeDoc.md5_hash == md5_str,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="文件已存在，请勿重复上传",
        )

    # 上传到用户专属知识库
    kb_svc = _get_kb_service(current_user.id)
    result_msg = kb_svc.upload_bt_str(text, file.filename)

    # 如果 Chroma 层也返回重复（双重保险）
    if "已经存在" in result_msg:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result_msg,
        )

    # 记录到 MySQL
    # 从返回消息中提取分块数量（格式："上传成功，共 {n} 个语义块"）
    import re
    chunk_count = 0
    match = re.search(r'共\s*(\d+)\s*个语义块', result_msg)
    if match:
        chunk_count = int(match.group(1))

    doc_record = KnowledgeDoc(
        user_id=current_user.id,
        filename=file.filename,
        md5_hash=md5_str,
        chunk_count=chunk_count,
    )
    session.add(doc_record)
    await session.commit()

    return {
        "message": result_msg,
        "filename": file.filename,
        "md5": md5_str,
        "chunk_count": chunk_count,
    }


@router.get("/documents")
async def list_documents(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """获取当前用户已上传的文档列表。"""
    result = await session.execute(
        select(KnowledgeDoc)
        .where(KnowledgeDoc.user_id == current_user.id)
        .order_by(KnowledgeDoc.created_at.desc())
    )
    docs = [
        {
            "id": doc.id,
            "filename": doc.filename,
            "md5_hash": doc.md5_hash,
            "chunk_count": doc.chunk_count,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        }
        for doc in result.scalars().all()
    ]
    return {"documents": docs, "total": len(docs)}


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    删除用户指定文档。

    注意：从 Chroma 中删除 chunks 较为复杂（Chroma 不支持按 metadata 批量删除），
    当前版本仅删除 MySQL 中的元数据记录。未来可扩展为按文档 ID 重建 collection。
    """
    result = await session.execute(
        select(KnowledgeDoc).where(
            KnowledgeDoc.id == doc_id,
            KnowledgeDoc.user_id == current_user.id,
        )
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文档不存在或无权访问",
        )

    await session.delete(doc)
    await session.commit()

    return {"message": f"文档 '{doc.filename}' 已删除"}
