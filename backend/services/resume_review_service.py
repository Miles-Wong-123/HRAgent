"""上传简历并固定本次审查依据的已发布 JD。"""
import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import fitz
from fastapi import HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.dependencies import CurrentUser
from backend.services.upload_storage import store_upload

_REVIEW_SELECT = """
    SELECT r.id, r.resume_id, r.position_id, r.jd_id, j.version AS jd_version,
           r.status, r.requested_by, r.created_at, s.original_filename, s.page_count,
           s.file_size_bytes
    FROM public.resume_reviews r
    JOIN public.resumes s ON s.tenant_id=r.tenant_id AND s.id=r.resume_id
    JOIN public.job_descriptions j ON j.tenant_id=r.tenant_id AND j.id=r.jd_id
"""


def _pdf_pages(path: Path, max_pages: int) -> int:
    try:
        with fitz.open(path) as pdf:
            if not pdf.is_pdf or pdf.needs_pass:
                raise HTTPException(422, "请上传有效且未加密的 PDF 简历")
            if not 1 <= pdf.page_count <= max_pages:
                raise HTTPException(422, f"简历须为 1 至 {max_pages} 页")
            has_text = False
            for page in pdf:
                if page.get_text().strip():
                    has_text = True
                elif page.get_images():
                    raise HTTPException(422, "简历包含扫描页，请先转成可复制文字的 PDF")
            if not has_text:
                raise HTTPException(422, "简历未包含可读取的文字")
            return pdf.page_count
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, "PDF 无法读取，请检查文件或重新导出") from exc


async def get_review(db: AsyncSession, tenant: str, review_id: UUID) -> dict:
    result = await db.execute(text(_REVIEW_SELECT + " WHERE r.tenant_id=:tenant AND r.id=:id"),
                              {"tenant": tenant, "id": review_id})
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "审查任务不存在")
    return dict(row)


async def list_reviews(db: AsyncSession, tenant: str, position_id: UUID, limit: int, offset: int) -> list[dict]:
    result = await db.execute(text(_REVIEW_SELECT + """
        WHERE r.tenant_id=:tenant AND r.position_id=:position
        ORDER BY r.created_at DESC, r.id DESC LIMIT :limit OFFSET :offset
    """), {"tenant": tenant, "position": position_id, "limit": limit, "offset": offset})
    return [dict(row) for row in result.mappings()]


async def create_review(db: AsyncSession, user: CurrentUser, position_id: UUID,
                        file: UploadFile, request_key: UUID) -> tuple[dict, bool]:
    settings = get_settings()
    await db.rollback()  # 上传和检验文件期间释放鉴权查询的连接。
    metadata, path = await store_upload(file, "resumes", set(settings.allowed_resume_extensions) & {".pdf"},
                                        "请上传 PDF 格式的简历")
    keep_file = False
    try:
        pages = await asyncio.to_thread(_pdf_pages, path, settings.resume_max_pages)
        params = {"tenant": user["tenant_id"], "user": UUID(user["user_id"]),
                  "position": position_id, "request_key": request_key}
        # 同一请求的并发重试串行化。已成功的请求始终返回原先绑定的 JD。
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                         {"key": f"resume-upload:{user['tenant_id']}:{request_key}"})
        previous = (await db.execute(text("""
            SELECT r.id, r.position_id, r.requested_by, s.file_sha256
            FROM public.resume_reviews r JOIN public.resumes s ON s.tenant_id=r.tenant_id AND s.id=r.resume_id
            WHERE r.tenant_id=:tenant AND r.request_key=:request_key
        """), params)).mappings().one_or_none()
        if previous:
            if (previous["position_id"], previous["requested_by"], previous["file_sha256"]) != (
                position_id, params["user"], metadata["file_sha256"]
            ):
                raise HTTPException(409, "此请求编号已用于另一次简历上传")
            return await get_review(db, params["tenant"], previous["id"]), False

        # JD 发布先锁岗位。此处先取得共享锁，再用新查询读取已提交的发布版本。
        position = await db.execute(text("""
            SELECT id FROM public.positions WHERE tenant_id=:tenant AND id=:position FOR SHARE
        """), params)
        if position.scalar_one_or_none() is None:
            raise HTTPException(404, "岗位不存在")
        published = await db.execute(text("""
            SELECT id FROM public.job_descriptions WHERE tenant_id=:tenant AND position_id=:position
            AND publication_status='published' FOR SHARE
        """), params)
        jd_id = published.scalar_one_or_none()
        if jd_id is None:
            raise HTTPException(409, "该岗位尚无已发布的 JD，请先审核并发布岗位 JD")

        resume_id, review_id = uuid4(), uuid4()
        await db.execute(text("""
            INSERT INTO public.resumes
                (id, tenant_id, uploaded_by, original_filename, storage_key, file_size_bytes, file_sha256, page_count)
            VALUES (:resume, :tenant, :user, :original_filename, :storage_key, :file_size_bytes, :file_sha256, :pages)
        """), {**params, **metadata, "resume": resume_id, "pages": pages})
        await db.execute(text("""
            INSERT INTO public.resume_reviews (id, tenant_id, resume_id, position_id, jd_id, requested_by, request_key)
            VALUES (:review, :tenant, :resume, :position, :jd, :user, :request_key)
        """), {**params, "review": review_id, "resume": resume_id, "jd": jd_id})
        detail = await get_review(db, params["tenant"], review_id)
        try:
            await db.commit()
        except asyncio.CancelledError:
            keep_file = True  # 数据库可能已提交，保留原件以便核对。
            raise
        except DBAPIError as exc:
            keep_file = exc.connection_invalidated
            raise
        keep_file = True
        return detail, True
    finally:
        if not keep_file:
            path.unlink(missing_ok=True)
