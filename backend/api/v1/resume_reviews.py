"""简历审查任务入口，限定为登录用户所属公司。"""
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.resume.state import ResumeReport
from backend.services.resume_assessment_service import claim_match, read_match, run_match
from backend.core.permissions import require_hr
from backend.dependencies import CurrentUser, get_db
from backend.services.resume_review_service import create_review, get_review, list_reviews

router = APIRouter()


class ResumeReview(BaseModel):
    id: UUID
    resume_id: UUID
    position_id: UUID
    jd_id: UUID
    jd_version: int
    status: Literal["pending", "processing", "completed", "failed"]
    original_filename: str
    page_count: int
    file_size_bytes: int
    requested_by: UUID
    created_at: datetime


@router.post("", response_model=ResumeReview, status_code=201, summary="上传简历并创建审查任务",
             responses={200: {"model": ResumeReview, "description": "重试已成功的上传，返回原任务"}})
async def upload_resume(
    response: Response, position_id: UUID = Form(...), file: UploadFile = File(...),
    request_key: UUID | None = Form(None, description="重试时复用同一编号，避免重复创建"),
    user: CurrentUser = Depends(require_hr), db: AsyncSession = Depends(get_db),
):
    """由后端选择当前已发布 JD，返回 pending 任务。上传后可使用 /match 启动六维度评审。"""
    try:
        review, created = await create_review(db, user, position_id, file, request_key or uuid4())
        response.status_code = 201 if created else 200
        return review
    finally:
        await file.close()


@router.get("", response_model=list[ResumeReview], summary="查看岗位的简历审查任务")
async def read_reviews(position_id: UUID, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                       user: CurrentUser = Depends(require_hr), db: AsyncSession = Depends(get_db)):
    return await list_reviews(db, user["tenant_id"], position_id, limit, offset)


@router.get("/{review_id}", response_model=ResumeReview, summary="查看简历审查任务状态")
async def read_review(review_id: UUID, user: CurrentUser = Depends(require_hr), db: AsyncSession = Depends(get_db)):
    return await get_review(db, user["tenant_id"], review_id)


class ResumeMatchResult(BaseModel):
    review_id: UUID
    jd_id: UUID
    jd_version: int
    resume_id: UUID
    status: Literal["pending", "processing", "completed", "failed"]
    match_started_at: datetime | None
    match_finished_at: datetime | None
    match_error: str | None
    requirement_results: list[dict] | None  # 旧任务的历史逐项报告
    six_dimension_report: ResumeReport | None


@router.post("/{review_id}/match", response_model=ResumeMatchResult, status_code=202,
             summary="后台启动简历六维度评审",
             responses={200: {"model": ResumeMatchResult, "description": "返回已有的匹配结果"}})
async def start_resume_match(review_id: UUID, background_tasks: BackgroundTasks, response: Response,
                             user: CurrentUser = Depends(require_hr), db: AsyncSession = Depends(get_db)):
    detail, attempt = await claim_match(db, user["tenant_id"], review_id)
    if attempt is not None:
        background_tasks.add_task(run_match, user["tenant_id"], review_id, attempt)
    if detail["status"] == "completed":
        response.status_code = 200
    return detail


@router.get("/{review_id}/match", response_model=ResumeMatchResult, summary="查看六维度评分与综合评语")
async def get_resume_match(review_id: UUID, user: CurrentUser = Depends(require_hr),
                           db: AsyncSession = Depends(get_db)):
    return await read_match(db, user["tenant_id"], review_id)
