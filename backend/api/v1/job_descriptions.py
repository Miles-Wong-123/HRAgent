"""JD 接口：保存输入、显式启动解析、查询草稿；所有操作限定本公司。"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.jd.nodes import MAX_TEXT_CHARACTERS
from backend.agents.jd.state import JDRuleInput, JDRuleSuggestions, JDReviewDecision, JDParseError, JDParseStatus, JDStructured, JDTextBlock, JDValidationIssue, JDEvidence, RequirementCategory, RequirementImportance
from backend.core.permissions import require_hr
from backend.dependencies import CurrentUser, get_db
from backend.services.job_description_service import (
    create_jd, get_jd, list_jds, prepare_jd_parse, run_jd_review, run_jd_parse_task, save_upload, suggest_missing_rules,
)

router = APIRouter()


class JDTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    position_id: UUID
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARACTERS, description="完整 JD 原文")


class JDSummary(BaseModel):
    id: UUID
    position_id: UUID
    version: int
    position_title_snapshot: str
    source_type: Literal["text", "file"]
    original_filename: str | None
    file_format: str | None
    parse_status: JDParseStatus
    publication_status: Literal["draft", "published", "archived"]
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    parse_started_at: datetime | None
    parse_finished_at: datetime | None

    @computed_field
    @property
    def review_status(self) -> Literal["not_ready", "awaiting_review", "published", "archived"]:
        if self.publication_status != "draft":
            return self.publication_status
        if self.parse_status == "completed":
            return "awaiting_review"
        return "not_ready"


class JDRequirementResponse(BaseModel):
    id: UUID
    sort_order: int
    description: str
    category: RequirementCategory
    importance: RequirementImportance
    evidence: list[JDEvidence]
    source: Literal["ai", "manual"]
    clarification: str | None
    evaluation_rule: str | None
    weight: Decimal | None
    confirmed_by: UUID | None
    confirmed_at: datetime | None


class JDDetail(JDSummary):
    suggested_weights: dict[Literal["required", "preferred"], int] = Field(
        default_factory=lambda: {"required": 2, "preferred": 1},
        description="按重要性给出的审核建议；每条条件的最终权重由 HR 在发布时确认。",
    )
    published_by: UUID | None
    published_at: datetime | None
    source_text: str | None
    raw_text: str | None
    text_blocks: list[JDTextBlock]
    page_count: int | None
    extraction_complete: bool
    structured_data: JDStructured | None
    reviewed_data: dict | None
    warnings: list[str]
    validation_issues: list[JDValidationIssue]
    error: JDParseError | None
    model_name: str | None
    prompt_version: str | None
    requirements: list[JDRequirementResponse]


class JDParseAccepted(BaseModel):
    id: UUID
    parse_status: Literal["extracting"]
    status_url: str
    poll_after_seconds: int = 2
    message: str = "解析已受理，请查询状态获取结果"


@router.post("/text", response_model=JDDetail, status_code=status.HTTP_201_CREATED)
async def submit_text(
    request: JDTextRequest,
    user: CurrentUser = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
):
    """保存粘贴文本为新版本（pending），再调用 /{jd_id}/parse 开始解析。"""
    return await create_jd(db, user, request.position_id, {"kind": "text", "source_text": request.text})


@router.post("/file", response_model=JDDetail, status_code=status.HTTP_201_CREATED)
async def submit_file(
    position_id: UUID = Form(...),
    file: UploadFile = File(..., description="PDF、DOCX、TXT 或 Markdown"),
    user: CurrentUser = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
):
    """保存文件为新版本，文件仅保存在服务器受控目录，不对外公开路径。"""
    saved_path = None
    try:
        source, saved_path = await save_upload(file)
        result = await create_jd(db, user, position_id, source)
        # 在返回成功前提交；失败时可以一并清除本次新上传的文件。
        await db.commit()
        return result
    except BaseException:
        await db.rollback()
        if saved_path is not None:
            saved_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get("", response_model=list[JDSummary])
async def read_jd_versions(
    position_id: UUID,
    user: CurrentUser = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """查询本公司指定岗位的 JD 历史版本，按版本号倒序。"""
    return await list_jds(db, user["tenant_id"], position_id, limit, offset)


@router.get("/{jd_id}", response_model=JDDetail)
async def read_jd(
    jd_id: UUID,
    user: CurrentUser = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
):
    """查询原文、解析状态、错误、模型草稿和待确认条件。"""
    return await get_jd(db, user["tenant_id"], jd_id)


@router.post("/{jd_id}/parse", response_model=JDParseAccepted, status_code=status.HTTP_202_ACCEPTED)
async def start_parse(
    jd_id: UUID,
    background_tasks: BackgroundTasks,
    response: Response,
    user: CurrentUser = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
):
    """提交后台解析任务，立即返回 202，不等待模型完成，不自动发布。

    失败或 needs_ocr 可重新调用；处理中重复调用返回 409。
    每隔约 2 秒 GET status_url，直到 completed / needs_ocr / failed。
    202 只表示受理成功，不代表已经解析成功。
    """
    # get_current_user 的查询使用同一个依赖会话，先结束只读事务并归还连接。
    # 解析服务只在开始和保存时短暂获取自己的数据库会话。
    await db.rollback()
    request, title, started = await prepare_jd_parse(user, jd_id)
    background_tasks.add_task(run_jd_parse_task, request, title, started)
    status_url = f"/api/v1/job-descriptions/{jd_id}"
    response.headers["Location"] = status_url
    response.headers["Retry-After"] = "2"
    return JDParseAccepted(id=jd_id, parse_status="extracting", status_url=status_url)


@router.post("/{jd_id}/review", response_model=JDDetail, summary="HR 审核并发布 JD")
async def review_and_publish(
    jd_id: UUID,
    decision: JDReviewDecision,
    user: CurrentUser = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
):
    """HR 或管理员确认发布本公司的草稿。同岗位之前发布的版本将归档。

    从 JD 详情复制每个 requirements[].id 到 requirement_id，逐条指定重要性、
    评估规则与相对权重。可选填 description、category 或 position_edits 修改草稿。
    手动新增条件省略 ID 并填写描述和类别；明确删除的 ID 放入 remove_requirement_ids。
    重复或遗漏条件返回 422；已发布、归档或未解析完成返回 409。
    """
    await db.rollback()
    await run_jd_review(user["tenant_id"], jd_id, decision, reviewer=UUID(user["user_id"]))
    return await get_jd(db, user["tenant_id"], jd_id)


@router.post("/{jd_id}/rule-suggestions", response_model=JDRuleSuggestions, summary="为草稿条件生成评估建议")
async def draft_evaluation_rules(
    jd_id: UUID,
    items: Annotated[list[JDRuleInput], Field(min_length=1)],
    user: CurrentUser = Depends(require_hr),
    db: AsyncSession = Depends(get_db),
):
    """按输入顺序编号（从 0 开始）。建议返回审核表单，由 HR 确认发布时保存。"""
    return await suggest_missing_rules(db, user["tenant_id"], jd_id, items)
