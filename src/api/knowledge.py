"""
知识库 API 路由

POST   /api/knowledge/upload        — 上传文档（TXT / PDF / DOCX / XLSX）
GET    /api/knowledge/documents     — 获取文档列表
DELETE /api/knowledge/documents/{id} — 删除文档（含 Chroma 向量清理 + 原文件删除）

v3.3.0:
- 支持 PDF / DOCX / XLSX 上传（parser + cleaner）
- 用户上传的原文件保存到 data/uploads/{user_id}/
- 分块策略改为通用 RecursiveCharacterTextSplitter
"""

import logging
import os
import time

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.database import get_async_session
from src.db.models import User, KnowledgeDoc
from src.auth.security import get_current_user
from src.knowledge import KnowledgeBaseService, get_string_md5
from src.knowledge.parser import parse_document, SUPPORTED_EXTENSIONS
from src.knowledge.cleaner import clean_text

import src.config as config

router = APIRouter(prefix="/api/knowledge", tags=["知识库"])

# 上传文件大小上限：10 MB
MAX_UPLOAD_SIZE = 10 * 1024 * 1024

logger = logging.getLogger("api.knowledge")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(_h)


def _get_kb_service(user_id: int) -> KnowledgeBaseService:
    """获取用户隔离的知识库服务实例。"""
    collection_name = config.get_user_collection_name(user_id)
    return KnowledgeBaseService(collection_name=collection_name)


def _get_ext(filename: str) -> str:
    """提取小写文件扩展名。"""
    idx = filename.rfind(".")
    return filename[idx:].lower() if idx != -1 else ""


# ================================================================
# Upload
# ================================================================

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(..., description="文档文件（TXT / PDF / DOCX / XLSX）"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    上传文档到用户的知识库。

    支持的格式: TXT, PDF, DOCX, XLSX

    流程:
    1. 校验文件格式与大小
    2. 保存原文件到 data/uploads/{user_id}/
    3. 解析文件提取纯文本（parser）
    4. 数据清洗（cleaner）
    5. 计算 MD5 + MySQL 用户级去重
    6. 通用语义分块 + 异步写入 Chroma
    7. 记录到 MySQL knowledge_docs 表
    """
    filename = file.filename
    ext = _get_ext(filename)

    # ---- 1. 校验文件格式 ----
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件格式: {ext}（支持: {', '.join(SUPPORTED_EXTENSIONS)}）",
        )

    # ---- 2. 读取文件字节并校验大小 ----
    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件过大，最大支持 {MAX_UPLOAD_SIZE // (1024 * 1024)} MB",
        )

    # ---- 3. 保存原文件 ----
    saved_path = _save_original_file(file_bytes, filename, current_user.id)

    # ---- 4. 解析文档提取纯文本 ----
    try:
        raw_text = parse_document(file_bytes, filename)
    except Exception as e:
        logger.error("文档解析失败: filename=%s, error=%s", filename, e)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"文档解析失败: {str(e)}",
        )

    if not raw_text or not raw_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="文档内容为空或无法提取文字（扫描版 PDF 请先 OCR）",
        )

    # ---- 5. 数据清洗 ----
    cleaned_text = clean_text(raw_text, filename)

    # ---- 6. 计算 MD5 + 用户级去重 ----
    md5_str = get_string_md5(cleaned_text)
    result = await session.execute(
        select(KnowledgeDoc).where(
            KnowledgeDoc.user_id == current_user.id,
            KnowledgeDoc.md5_hash == md5_str,
        )
    )
    if result.scalar_one_or_none():
        # 去重：删除刚保存的原文件
        _delete_file(saved_path)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="文件已存在，请勿重复上传",
        )

    # ---- 7. 先记录到 MySQL（权威源）----
    # MySQL 作为权威数据源，先写入记录。如果后续 Chroma 写入失败，回滚 MySQL 记录。
    doc_record = KnowledgeDoc(
        user_id=current_user.id,
        filename=filename,
        md5_hash=md5_str,
        chunk_count=0,  # 先占位，Chroma 上传成功后更新
    )
    session.add(doc_record)
    await session.commit()
    await session.refresh(doc_record)

    # ---- 8. 上传到 Chroma 知识库 ----
    kb_svc = _get_kb_service(current_user.id)
    operator = current_user.username or str(current_user.id)
    try:
        upload_result = await kb_svc.upload_bt_str(
            data=cleaned_text,
            filename=filename,
            md5_str=md5_str,
            operator=operator,
        )

        if not upload_result["success"]:
            # Chroma 写入失败 → 回滚 MySQL 记录 + 删除原文件
            await session.delete(doc_record)
            await session.commit()
            _delete_file(saved_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=upload_result["message"],
            )

        chunk_count = upload_result["chunk_count"]
        doc_record.chunk_count = chunk_count
        await session.commit()

    except HTTPException:
        raise
    except Exception as e:
        # Chroma 异常 → 回滚 MySQL 记录 + 删除原文件
        logger.error("Chroma 上传失败，回滚 MySQL 记录: filename=%s, error=%s", filename, e)
        await session.delete(doc_record)
        await session.commit()
        _delete_file(saved_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"知识库写入失败: {str(e)}",
        )

    logger.info("上传成功: user=%s, filename=%s, chunks=%d, saved=%s",
                current_user.id, filename, chunk_count, saved_path)

    return {
        "message": upload_result["message"],
        "filename": filename,
        "md5": md5_str,
        "chunk_count": chunk_count,
        "saved_path": saved_path,
    }


# ================================================================
# List
# ================================================================

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


# ================================================================
# Delete
# ================================================================

@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    删除用户指定文档。

    流程:
    1. 查询 MySQL 文档记录
    2. 清理 Chroma 向量数据
    3. 删除原文件（如有）
    4. 删除 MySQL 记录
    """
    # 1. 查询文档记录
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

    # 2. 清理 Chroma 向量数据
    kb_svc = _get_kb_service(current_user.id)
    deleted_chunks = 0
    try:
        deleted_chunks = await kb_svc.delete_by_doc_id(doc.md5_hash)
    except Exception as e:
        logger.warning(
            "Chroma 清理失败: doc_id=%d, md5=%s, error=%s",
            doc_id, doc.md5_hash, e,
        )

    # 3. 尝试删除原文件（根据文件名 + 用户 ID 查找）
    _delete_original_file(doc.filename, current_user.id)

    # 4. 删除 MySQL 记录
    await session.delete(doc)
    await session.commit()

    return {
        "message": f"文档 '{doc.filename}' 已删除",
        "deleted_chunks": deleted_chunks,
    }


# ================================================================
# 文件存储辅助函数
# ================================================================

def _get_user_upload_dir(user_id: int) -> str:
    """获取用户上传原文件的目录，确保存在。"""
    user_dir = os.path.join(config.upload_dir, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


def _save_original_file(file_bytes: bytes, filename: str, user_id: int) -> str:
    """
    保存用户上传的原文件。

    命名规则: {timestamp}_{original_filename}
    返回保存的绝对路径。
    """
    user_dir = _get_user_upload_dir(user_id)
    ts = int(time.time() * 1000)  # 毫秒时间戳
    safe_name = f"{ts}_{filename}"
    save_path = os.path.join(user_dir, safe_name)
    with open(save_path, "wb") as f:
        f.write(file_bytes)
    logger.info("原文件已保存: %s (%d bytes)", save_path, len(file_bytes))
    return save_path


def _delete_file(path: str) -> None:
    """安全删除文件，不抛异常。"""
    try:
        if path and os.path.isfile(path):
            os.remove(path)
            logger.info("已删除文件: %s", path)
    except Exception as e:
        logger.warning("删除文件失败: %s, error=%s", path, e)


def _delete_original_file(filename: str, user_id: int) -> None:
    """
    根据文件名和用户 ID 查找并删除原文件。
    由于文件名带时间戳前缀，使用 glob 匹配。
    """
    import glob as glob_m
    user_dir = _get_user_upload_dir(user_id)
    pattern = os.path.join(user_dir, f"*_{filename}")
    for match in glob_m.glob(pattern):
        _delete_file(match)
